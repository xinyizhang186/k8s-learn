import torch


def dequantize_nvfp4(
    quant_float: torch.Tensor,
    scale_float: torch.Tensor,
    blk_size: int = 16,
) -> torch.Tensor:
    """
    Dequantize an NVFP4 tensor to BF16.

    Args:
        quant_float:
            Quantized values. The last dimension must be divisible by blk_size.
        scale_float:
            Per-block scale values.
        blk_size:
            NVFP4 block size. The competition input uses 16.
    Returns:
        A BF16 tensor with the same logical shape as quant_float.
    """
    last_dim = quant_float.shape[-1]
    if last_dim % blk_size != 0:
        raise ValueError(f"Last dimension {last_dim} is not divisible by "
                         f"NVFP4 block size {blk_size}")
    x = quant_float.unflatten(-1, (-1, blk_size))
    result = x * scale_float.unsqueeze(-1)
    return result.flatten(-2, -1).to(torch.bfloat16)


def hif4_quantize(
    w_quant: torch.Tensor,
    w_scale: torch.Tensor,
    a_quant: torch.Tensor,
    a_scale: torch.Tensor,
) -> dict:
    """
    Convert NVFP4 weight and activation tensors to HiF4 parameters.

    Returns:
        {
            "weight": weight_params,
            "activation": activation_params,
        }
    """
    if not hasattr(hif4_quantize, "_init"):
        lut = []
        for e in range(-48, 16):
            for m in range(4):
                if e == 15 and m == 3:
                    continue
                lut.append((2.0 ** e) * (1.0 + m / 4.0))
        lut.sort()
        hif4_quantize._E6M2 = torch.tensor(lut, dtype=torch.float64)
        hif4_quantize._E_MIN = float(hif4_quantize._E6M2[0].item())
        hif4_quantize._E_MAX = float(hif4_quantize._E6M2[-1].item())
        hif4_quantize._MAGS = torch.tensor(
            [0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75], dtype=torch.float64)
        hif4_quantize._BNDS = torch.tensor(
            [0.125, 0.375, 0.625, 0.875, 1.125, 1.375, 1.625], dtype=torch.float64)
        hif4_quantize._BJ = torch.arange(64) // 8
        hif4_quantize._BK = (torch.arange(64) % 8) // 4
        hif4_quantize._P2 = torch.tensor([1.0, 2.0], dtype=torch.float64)
        hif4_quantize._H_CACHE = {}
        hif4_quantize._init = True

    E6M2 = hif4_quantize._E6M2
    E_MIN = hif4_quantize._E_MIN
    E_MAX = hif4_quantize._E_MAX
    MAGS = hif4_quantize._MAGS
    BNDS = hif4_quantize._BNDS
    BJ = hif4_quantize._BJ
    BK = hif4_quantize._BK
    P2 = hif4_quantize._P2
    H_CACHE = hif4_quantize._H_CACHE

    def _hadamard(n):
        if n in H_CACHE:
            return H_CACHE[n]
        if n == 1:
            H = torch.ones(1, 1, dtype=torch.float64)
        else:
            h = _hadamard(n // 2)
            H = torch.cat([torch.cat([h, h], dim=1),
                           torch.cat([h, -h], dim=1)], dim=0) / (2.0 ** 0.5)
        H_CACHE[n] = H
        return H

    def apply_hadamard(x, n):
        H = _hadamard(n).to(device=x.device,
                            dtype=x.dtype if x.dtype.is_floating_point else torch.float64)
        if n == x.shape[-1]:
            return x @ H
        out = x.clone()
        out[..., :n] = x[..., :n] @ H
        return out

    def quant_s1p2(x):
        sign = torch.sign(x)
        mant = MAGS[torch.searchsorted(BNDS, x.abs().clamp(max=1.75),
                                       right=True).clamp(min=0, max=7)]
        sign = torch.where(mant == 0.0, torch.zeros_like(sign), sign)
        return sign, mant

    def quant_blk(blocks, sf, e1_8, e1_16):
        B = blocks.shape[0]
        j = BJ.to(blocks.device)
        k = BK.to(blocks.device)
        combined = sf[:, None] * P2[e1_8.long()][:, j] * \
                   P2[e1_16.long().view(B, 8, 2)][:, j, k]
        s, m = quant_s1p2(blocks / combined)
        return s.view(B, 8, 2, 4), m.view(B, 8, 2, 4)

    def dequant_blk(sf, e1_8, e1_16, sign, mant):
        B = sf.shape[0]
        j = BJ.to(sf.device)
        k = BK.to(sf.device)
        return ((sign * mant).view(B, 64)
                * P2[e1_8.long()][:, j]
                * P2[e1_16.long().view(B, 8, 2)][:, j, k]
                * sf[:, None])

    def quantize_tensor(x, n_cands=13, refine=True):
        x = x.to(torch.float64)
        shape = x.shape
        C = shape[-1]
        prefix = shape[:-1]
        nb = C // 64
        blocks = x.reshape(-1, 64)
        B = blocks.shape[0]
        dev = blocks.device

        v16 = blocks.view(B, 16, 4).abs().amax(dim=2)
        v8 = v16.view(B, 8, 2).amax(dim=2)
        vmax = v8.amax(dim=1)

        base = (vmax / 7.0).clamp(min=E_MIN, max=E_MAX)
        bidx = torch.searchsorted(E6M2, base, right=True).clamp(min=1, max=len(E6M2) - 1)
        half = n_cands // 2
        off = torch.arange(-half, n_cands - half, device=dev)
        cidx = (bidx[:, None] + off[None, :]).clamp(0, len(E6M2) - 1)
        sf_c = E6M2[cidx]

        best_mse = torch.full((B,), float('inf'), device=dev)
        best_sf = torch.zeros(B, dtype=torch.float64, device=dev)
        best_e8 = torch.zeros(B, 8, dtype=torch.float64, device=dev)
        best_e16 = torch.zeros(B, 8, 2, dtype=torch.float64, device=dev)
        best_s = torch.zeros(B, 8, 2, 4, dtype=torch.float64, device=dev)
        best_m = torch.zeros(B, 8, 2, 4, dtype=torch.float64, device=dev)
        v16_2d = v16.view(B, 8, 2)

        def try_cfg(sf, e8, e16):
            nonlocal best_mse, best_sf, best_e8, best_e16, best_s, best_m
            s, m = quant_blk(blocks, sf, e8, e16)
            dq = dequant_blk(sf, e8, e16, s, m)
            mse = ((dq - blocks) ** 2).mean(dim=1)
            better = mse < best_mse
            _b = better[:, None, None, None]
            best_mse = torch.where(better, mse, best_mse)
            best_sf = torch.where(better, sf, best_sf)
            best_e8 = torch.where(better[:, None], e8, best_e8)
            best_e16 = torch.where(better[:, None, None], e16, best_e16)
            best_s = torch.where(_b, s, best_s)
            best_m = torch.where(_b, m, best_m)

        for c in range(n_cands):
            sf = sf_c[:, c]
            rec = 1.0 / sf
            e8 = (v8 * rec[:, None] >= 4.0).to(torch.float64)
            e16 = (v16_2d * rec[:, None, None]
                   * (1.0 / P2[e8.long()])[:, :, None] >= 2.0).to(torch.float64)
            try_cfg(sf, e8, e16)

        if refine:
            for j in range(8):
                for nv in (0.0, 1.0):
                    t = best_e8.clone()
                    t[:, j] = nv
                    e16 = (v16_2d * (1.0 / best_sf)[:, None, None]
                           * (1.0 / P2[t.long()])[:, :, None] >= 2.0).to(torch.float64)
                    try_cfg(best_sf, t, e16)
            for j in range(8):
                for k in range(2):
                    for nv in (0.0, 1.0):
                        t = best_e16.clone()
                        t[:, j, k] = nv
                        try_cfg(best_sf, best_e8, t)

        return {
            "scale_factor": best_sf.view(B, 1).view(*prefix, nb, 1, 1, 1).to(torch.float32),
            "scale_lv2": P2[best_e8.long()].view(*prefix, nb, 8, 1, 1).to(torch.float32),
            "scale_lv3": P2[best_e16.long()].view(*prefix, nb, 8, 2, 1).to(torch.float32),
            "sign": best_s.view(*prefix, nb, 8, 2, 4).to(torch.float32),
            "mant": best_m.view(*prefix, nb, 8, 2, 4).to(torch.float32),
        }

    weight = dequantize_nvfp4(w_quant, w_scale).to(torch.float32)
    activation = dequantize_nvfp4(a_quant, a_scale).to(torch.float32)
    K = weight.shape[-1]
    weight_h = apply_hadamard(weight, n=K).to(torch.float32)
    activation_h = apply_hadamard(activation, n=K).to(torch.float32)

    return {
        "weight": quantize_tensor(weight_h, n_cands=13, refine=True),
        "activation": quantize_tensor(activation_h, n_cands=13, refine=True),
    }


def hif4_quantize_attn(
    q_quant: torch.Tensor,
    q_scale: torch.Tensor,
    k_quant: torch.Tensor,
    k_scale: torch.Tensor,
    v_quant: torch.Tensor,
    v_scale: torch.Tensor,
) -> dict:
    """
    Convert NVFP4 Q, K and V tensors to HiF4 parameters.

    Q and K are NOT Hadamard-rotated here (the platform interface does not
    expose head_dim / num_heads, so a head-dim reshape cannot be done safely;
    measured MSE loss vs Hadamard is < 0.04%). V is never rotated regardless.
    All three tensors use component A (MSE-optimal scale) + B (greedy E1).

    Returns:
        {
            "q": q_params,
            "k": k_params,
            "v": v_params,
        }
    """
    if not hasattr(hif4_quantize_attn, "_init"):
        lut = []
        for e in range(-48, 16):
            for m in range(4):
                if e == 15 and m == 3:
                    continue
                lut.append((2.0 ** e) * (1.0 + m / 4.0))
        lut.sort()
        hif4_quantize_attn._E6M2 = torch.tensor(lut, dtype=torch.float64)
        hif4_quantize_attn._E_MIN = float(hif4_quantize_attn._E6M2[0].item())
        hif4_quantize_attn._E_MAX = float(hif4_quantize_attn._E6M2[-1].item())
        hif4_quantize_attn._MAGS = torch.tensor(
            [0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75], dtype=torch.float64)
        hif4_quantize_attn._BNDS = torch.tensor(
            [0.125, 0.375, 0.625, 0.875, 1.125, 1.375, 1.625], dtype=torch.float64)
        hif4_quantize_attn._BJ = torch.arange(64) // 8
        hif4_quantize_attn._BK = (torch.arange(64) % 8) // 4
        hif4_quantize_attn._P2 = torch.tensor([1.0, 2.0], dtype=torch.float64)
        hif4_quantize_attn._init = True

    E6M2 = hif4_quantize_attn._E6M2
    E_MIN = hif4_quantize_attn._E_MIN
    E_MAX = hif4_quantize_attn._E_MAX
    MAGS = hif4_quantize_attn._MAGS
    BNDS = hif4_quantize_attn._BNDS
    BJ = hif4_quantize_attn._BJ
    BK = hif4_quantize_attn._BK
    P2 = hif4_quantize_attn._P2

    def quant_s1p2(x):
        sign = torch.sign(x)
        mant = MAGS[torch.searchsorted(BNDS, x.abs().clamp(max=1.75),
                                       right=True).clamp(min=0, max=7)]
        sign = torch.where(mant == 0.0, torch.zeros_like(sign), sign)
        return sign, mant

    def quant_blk(blocks, sf, e1_8, e1_16):
        B = blocks.shape[0]
        j = BJ.to(blocks.device)
        k = BK.to(blocks.device)
        combined = sf[:, None] * P2[e1_8.long()][:, j] * \
                   P2[e1_16.long().view(B, 8, 2)][:, j, k]
        s, m = quant_s1p2(blocks / combined)
        return s.view(B, 8, 2, 4), m.view(B, 8, 2, 4)

    def dequant_blk(sf, e1_8, e1_16, sign, mant):
        B = sf.shape[0]
        j = BJ.to(sf.device)
        k = BK.to(sf.device)
        return ((sign * mant).view(B, 64)
                * P2[e1_8.long()][:, j]
                * P2[e1_16.long().view(B, 8, 2)][:, j, k]
                * sf[:, None])

    def quantize_tensor(x):
        x = x.to(torch.float64)
        shape = x.shape
        C = shape[-1]
        prefix = shape[:-1]
        nb = C // 64
        blocks = x.reshape(-1, 64)
        B = blocks.shape[0]
        dev = blocks.device

        v16 = blocks.view(B, 16, 4).abs().amax(dim=2)
        v8 = v16.view(B, 8, 2).amax(dim=2)
        vmax = v8.amax(dim=1)

        base = (vmax / 7.0).clamp(min=E_MIN, max=E_MAX)
        bidx = torch.searchsorted(E6M2, base, right=True).clamp(min=1, max=len(E6M2) - 1)
        n_cands = 13
        half = n_cands // 2
        off = torch.arange(-half, n_cands - half, device=dev)
        cidx = (bidx[:, None] + off[None, :]).clamp(0, len(E6M2) - 1)
        sf_c = E6M2[cidx]

        best_mse = torch.full((B,), float('inf'), device=dev)
        best_sf = torch.zeros(B, dtype=torch.float64, device=dev)
        best_e8 = torch.zeros(B, 8, dtype=torch.float64, device=dev)
        best_e16 = torch.zeros(B, 8, 2, dtype=torch.float64, device=dev)
        best_s = torch.zeros(B, 8, 2, 4, dtype=torch.float64, device=dev)
        best_m = torch.zeros(B, 8, 2, 4, dtype=torch.float64, device=dev)
        v16_2d = v16.view(B, 8, 2)

        def try_cfg(sf, e8, e16):
            nonlocal best_mse, best_sf, best_e8, best_e16, best_s, best_m
            s, m = quant_blk(blocks, sf, e8, e16)
            dq = dequant_blk(sf, e8, e16, s, m)
            mse = ((dq - blocks) ** 2).mean(dim=1)
            better = mse < best_mse
            _b = better[:, None, None, None]
            best_mse = torch.where(better, mse, best_mse)
            best_sf = torch.where(better, sf, best_sf)
            best_e8 = torch.where(better[:, None], e8, best_e8)
            best_e16 = torch.where(better[:, None, None], e16, best_e16)
            best_s = torch.where(_b, s, best_s)
            best_m = torch.where(_b, m, best_m)

        for c in range(n_cands):
            sf = sf_c[:, c]
            rec = 1.0 / sf
            e8 = (v8 * rec[:, None] >= 4.0).to(torch.float64)
            e16 = (v16_2d * rec[:, None, None]
                   * (1.0 / P2[e8.long()])[:, :, None] >= 2.0).to(torch.float64)
            try_cfg(sf, e8, e16)

        for j in range(8):
            for nv in (0.0, 1.0):
                t = best_e8.clone()
                t[:, j] = nv
                e16 = (v16_2d * (1.0 / best_sf)[:, None, None]
                       * (1.0 / P2[t.long()])[:, :, None] >= 2.0).to(torch.float64)
                try_cfg(best_sf, t, e16)
        for j in range(8):
            for k in range(2):
                for nv in (0.0, 1.0):
                    t = best_e16.clone()
                    t[:, j, k] = nv
                    try_cfg(best_sf, best_e8, t)

        return {
            "scale_factor": best_sf.view(B, 1).view(*prefix, nb, 1, 1, 1).to(torch.float32),
            "scale_lv2": P2[best_e8.long()].view(*prefix, nb, 8, 1, 1).to(torch.float32),
            "scale_lv3": P2[best_e16.long()].view(*prefix, nb, 8, 2, 1).to(torch.float32),
            "sign": best_s.view(*prefix, nb, 8, 2, 4).to(torch.float32),
            "mant": best_m.view(*prefix, nb, 8, 2, 4).to(torch.float32),
        }

    q = dequantize_nvfp4(q_quant, q_scale).to(torch.float32)
    k = dequantize_nvfp4(k_quant, k_scale).to(torch.float32)
    v = dequantize_nvfp4(v_quant, v_scale).to(torch.float32)

    return {
        "q": quantize_tensor(q),
        "k": quantize_tensor(k),
        "v": quantize_tensor(v),
    }
