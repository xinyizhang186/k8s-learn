from __future__ import annotations

import argparse
import importlib
import math
import os
import random
import sys
import time
import traceback
from typing import Any, Callable, Iterable

import torch

BF16_TOL = 0.01
BASE_RANDOM_SEED = 20260805
DEFAULT_DATASETS_DIR = os.environ.get(
    r"./本地调试参考/example",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "mini_sample"),
)

class CheckSummary:
    def __init__(self, passed: int = 0, failed: int = 0) -> None:
        self.passed = int(passed)
        self.failed = int(failed)

    @property
    def total(self) -> int:
        return self.passed + self.failed

    def add(self, ok: bool) -> None:
        if ok:
            self.passed += 1
        else:
            self.failed += 1

    def merge(self, other: "CheckSummary") -> None:
        self.passed += other.passed
        self.failed += other.failed

def _seed_everything(seed: int) -> None:
    seed = int(seed)
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    try:
        import numpy as np
        np.random.seed(seed % (2**32))
    except Exception:
        pass
    
def _case_random_seed(track_name: str, idx: int) -> int:
    track_offset = 0 if track_name == "linear" else 1_000_000
    return BASE_RANDOM_SEED + track_offset + int(idx)

def dequantize_nvfp4(quant_float: torch.Tensor, scale_float: torch.Tensor, scale_2: float = 1.0, blk_size: int = 16) -> torch.Tensor:
    c = quant_float.shape[-1]
    if c % blk_size != 0:
        raise ValueError(f"Last dim {c} not divisible by NVFP4 block size {blk_size}")
    if isinstance(scale_2, torch.Tensor):
        scale_2 = scale_2.item()
    x = quant_float.unflatten(-1, (-1, blk_size))
    result = x * scale_float.unsqueeze(-1) * float(scale_2)
    return result.flatten(-2, -1).to(torch.bfloat16)


def dequantize_hif4(params: dict[str, torch.Tensor], original_shape: Iterable[int]) -> torch.Tensor:
    dq = (
        params["sign"]
        * params["mant"]
        * params["scale_lv2"]
        * params["scale_lv3"]
        * params["scale_factor"]
    )
    return dq.reshape(tuple(int(s) for s in original_shape)).to(torch.bfloat16)

def _expected_hif4_param_shapes(original_shape: Iterable[int]) -> dict[str, tuple[int, ...]]:
    shape = tuple(int(s) for s in original_shape)
    if not shape:
        raise ValueError("original_shape must have at least one dimension")

    c = shape[-1]
    if c % 64 != 0:
        raise ValueError(f"Last dim {c} not divisible by HIF4 block size 64")

    prefix = shape[:-1] + (c // 64,)
    return {
        "scale_factor": prefix + (1, 1, 1),
        "scale_lv2": prefix + (8, 1, 1),
        "scale_lv3": prefix + (8, 2, 1),
        "sign": prefix + (8, 2, 4),
        "mant": prefix + (8, 2, 4),
    }


def validate_hif4_params(params, original_shape, tag = ""):
    errors = []

    try:
        expected_shapes = _expected_hif4_param_shapes(original_shape)
    except Exception as e:
        errors.append(f"{tag} {e}")
        return errors

    if not isinstance(params, dict):
        return [f"{tag} params must be a dict, got {type(params).__name__}"]

    tensors = {}

    for name, expected_shape in expected_shapes.items():
        if name not in params:
            errors.append(f"{tag} missing parameter: {name}")
            continue

        value = params[name]

        if not isinstance(value, torch.Tensor):
            errors.append(
                f"{tag} {name} must be a torch.Tensor, "
                f"got {type(value).__name__}"
            )
            continue

        actual_shape = tuple(value.shape)
        if actual_shape != expected_shape:
            errors.append(
               f"{tag} {name} shape {actual_shape} "
               f"!= expected {expected_shape}" 
            )
            continue

        if torch.is_complex(value):
            errors.append(
                f"{tag} {name} must be real-valued, got complex tensor"
            )
            continue

        try:
            tensors[name] = value.detach().to(
                dtype = torch.float64,
                device = "cpu",
            )
        except Exception as e:
            errors.append(
                f"{tag} failed to convert {name} for validation: {e}"
            )

    if errors:
        return errors

    for name, value in tensors.items():
        nonfinite = ~torch.isfinite(value)
        if nonfinite.any():
            cnt = nonfinite.sum().item()
            errors.append(
                f"{tag} {name} has {cnt} non-finite values"
            )

    if errors:
        return errors

    scale_factor = tensors["scale_factor"]
    scale_lv2 = tensors["scale_lv2"]
    scale_lv3 = tensors["scale_lv3"]
    sign = tensors["sign"]
    mant = tensors["mant"]

    try:
        dq = sign * mant * scale_lv2 * scale_lv3 * scale_factor
        dq_flat = dq.reshape(tuple(original_shape))
    except Exception as e:
        errors.append(
            f"{tag} Shape broadcasting/reshape failed: {e}"
        )
        return errors

    nonfinite_dq = ~torch.isfinite(dq_flat)
    if nonfinite_dq.any():
        cnt = nonfinite_dq.sum().item()
        errors.append(
            f"{tag} dequantized tensor has {cnt} non-finite values"
        )
        return errors

    expected_dq_numel = math.prod(tuple(original_shape))
    if dq_flat.numel() != expected_dq_numel:
        errors.append(
            f"{tag} Dequantized numel {dq_flat.numel()} "
            f"!= expected {expected_dq_numel}"
        )

    min_scale = 2.0 ** (-48)
    max_scale = 49152.0

    if (scale_factor < min_scale).any():
        cnt = (scale_factor < min_scale).sum().item()
        errors.append(
            f"{tag} scale_factor has {cnt} values below min 2^-48"
        )

    if (scale_factor > max_scale).any():
        cnt = (scale_factor > max_scale).sum().item()
        errors.append(
            f"{tag} scale_factor has {cnt} values above max 49152"
        )

    sf_clamped = scale_factor.clamp(min = 2.0 ** (-126))
    e_sf = torch.floor(torch.log2(sf_clamped))

    sf_e6m2 = (
        torch.round(
            scale_factor * (2.0 ** (2 - e_sf))
        )
        * (2.0 ** (e_sf - 2))
    )

    e6m2_matches = scale_factor == sf_e6m2

    if not e6m2_matches.all():
        cnt = (~e6m2_matches).sum().item()
        max_diff = torch.abs(
            scale_factor - sf_e6m2
        ).max().item()

        errors.append(
            f"{tag} scale_factor has {cnt} values "
            f"not in exact e6m2 format "
            f"(max_diff={max_diff:.4e})"
        )

    lv2_matches = (
        (scale_lv2 == 1.0)
        |  (scale_lv2 == 2.0)
    )

    if not lv2_matches.all():
        cnt = (~lv2_matches).sum().item()
        invalid_vals = scale_lv2[
            ~lv2_matches
        ].unique()
        
        errors.append(
            f"{tag} scale_lv2 has {cnt} values "
            f"not exactly in {{1.0, 2.0}}: "
            f"{invalid_vals.tolist()[:5]}"
        )

    lv3_matches = (
        (scale_lv3 == 1.0)
        |  (scale_lv3 == 2.0)
    )

    if not lv3_matches.all():
        cnt = (~lv3_matches).sum().item()
        invalid_vals = scale_lv3[
            ~lv3_matches
        ].unique()
        
        errors.append(
            f"{tag} scale_lv3 has {cnt} values "
            f"not exactly in {{1.0, 2.0}}: "
            f"{invalid_vals.tolist()[:5]}"
        )

    sign_matches = (
        (sign == -1.0)
        |  (sign == 0.0)
        | (sign == 1.0)
    )

    if not sign_matches.all():
        cnt = (~sign_matches).sum().item()
        invalid_vals = sign[
            ~sign_matches
        ].unique()
        
        errors.append(
            f"{tag} sign has {cnt} values "
            f"not exactly in {{-1.0, 0.0, 1.0}}: "
            f"{invalid_vals.tolist()[:5]}"
        )

    if (mant < 0.0).any():
        cnt = (mant < 0.0).sum().item()
        errors.append(
            f"{tag} mant has {cnt} negative values "
        )

    limit_val = 2.0 - 2.0 ** (-2)

    if (mant > limit_val).any():
        cnt = (mant > limit_val).sum().item()
        errors.append(
            f"{tag} mant has {cnt} values above max {limit_val}"
        )

    mant_scaled = mant * 4.0
    mant_rounded = torch.round(mant_scaled)

    mant_matches = mant_scaled == mant_rounded

    if not mant_matches.all():
        cnt = (~mant_matches).sum().item()
        invalid_vals = mant[
            ~mant_matches
        ].unique()
        
        errors.append(
            f"{tag} mant has {cnt} values "
            f"not exactly quantized to 0.25 steps: "
            f"{invalid_vals.tolist()[:5]}"
        )

    return errors

def _validate_reported_shape(result: dict[str, Any], key: str, original_shape: Iterable[int], tag: str) -> list[str]:
    if key not in result:
        return []

    try:
        reported_shape = tuple(int(s) for s in result[key])
    except Exception as exc:
        return [f"{tag} {key} is invalid: {exc}"]

    original_shape = tuple(int(s) for s in original_shape)
    if reported_shape != original_shape:
        return [f"{tag} {key} {reported_shape} must equal original shape {original_shape}"]
    return []


def validate_linear_result(result: Any, weight_shape: Iterable[int], activation_shape: Iterable[int]) -> list[str]:
    if not isinstance(result, dict):
        return [f"[Linear] result must be a dict, got {type(result).__name__}"]

    errors = []
    errors += _validate_reported_shape(result, "weight_concat_shape", weight_shape, "[Linear] weight")
    errors += _validate_reported_shape(result, "activation_concat_shape", activation_shape, "[Linear] activation")

    if "weight" not in result:
        errors.append("[Linear] result missing key: weight")
    else:
        errors += validate_hif4_params(result["weight"], weight_shape, "[Linear] weight")

    if "activation" not in result:
        errors.append("[Linear] result missing key: activation")
    else:
        errors += validate_hif4_params(result["activation"], activation_shape, "[Linear] activation")

    return errors

def validate_attn_result(
    result: Any,
    q_shape: Iterable[int], 
    k_shape: Iterable[int],
    v_shape: Iterable[int],
) -> list[str]:
    if not isinstance(result, dict):
        return [f"[Attn] result must be a dict, got {type(result).__name__}"]

    errors = []
    for name, shape in (("q", q_shape), ("k", k_shape), ("v", v_shape)):
        if name not in result:
            errors.append(f"[Attn] result missing key: {name}")
        else:
            errors += validate_hif4_params(result[name], shape, f"[Attn] {name}")
    return errors


def _validate_nvfp4_input(
    quant: torch.Tensor,
    scale: torch.Tensor,
    expected_shape: Iterable[int],
    tag: str,
) -> list[str]:
    try:
        restored = dequantize_nvfp4(quant, scale)
    except Exception as exc:
        return [f"{tag} input NVFP4 dequantization failed: {exc}"]

    expected_shape = tuple(int(s) for s in expected_shape)
    if tuple(restored.shape) != expected_shape:
        return [f"{tag} input shape {tuple(restored.shape)} != declared {expected_shape}"]
    return []


def check_linear_case(
    hif4_quantize: Callable[..., Any], group: dict[str, Any], idx: int
) -> tuple[bool, str]:
    required = (
        "weight_quant",
        "weight_scale",
        "activation_quant",
        "activation_scale",
        "weight_shape",
        "activation_shape",
    )
    missing = [name for name in required if name not in group]
    if missing:
        return False, f"sample is missing keys: {missing}"

    w_quant = group["weight_quant"]
    w_scale = group["weight_scale"]
    a_quant = group["activation_quant"]
    a_scale = group["activation_scale"]
    w_shape = tuple(group["weight_shape"])
    a_shape = tuple(group["activation_shape"])

    input_errors = []
    input_errors += _validate_nvfp4_input(w_quant, w_scale, w_shape, "[Linear] weight")
    input_errors += _validate_nvfp4_input(a_quant, a_scale, a_shape, "[Linear] activation")
    if input_errors:
        return False, "\n  ".join(input_errors)

    _seed_everything(_case_random_seed("linear", idx))
    start = time.perf_counter()
    try:
        result = hif4_quantize(w_quant, w_scale, a_quant, a_scale)
    except KeyboardInterrupt:
        raise
    except BaseException:
        return False, traceback.format_exc()
    runtime_ms = (time.perf_counter() - start) * 1000

    errors = validate_linear_result(result, w_shape, a_shape)
    if errors:
        return False, f"quantize={runtime_ms:.2f}ms\n " + "\n  ".join(errors)

    return True, f"quantize={runtime_ms:.2f}ms"

 
def check_attn_case(
    hif4_quantize_attn: Callable[..., Any], group: dict[str, Any], idx: int
) -> tuple[bool, str]:
    required = (
        "q_quant",
        "q_scale",
        "k_quant",
        "k_scale",
        "v_quant",
        "v_scale",
        "q_shape",
        "k_shape",
        "v_shape",
        "q_num_heads",
        "kv_num_heads",
        "head_dim",
    )
    missing = [name for name in required if name not in group]
    if missing:
        return False, f"sample is missing keys: {missing}"

    q_quant, q_scale = group["q_quant"], group["q_scale"]
    k_quant, k_scale = group["k_quant"], group["k_scale"]
    v_quant, v_scale = group["v_quant"], group["v_scale"]
    q_shape = tuple(group["q_shape"])
    k_shape = tuple(group["k_shape"])
    v_shape = tuple(group["v_shape"])

    q_num_heads = int(group["q_num_heads"])
    kv_num_heads = int(group["kv_num_heads"])
    head_dim = int(group["head_dim"])

    input_errors = []
    input_errors += _validate_nvfp4_input(q_quant, q_scale, q_shape, "[Attn] q")
    input_errors += _validate_nvfp4_input(k_quant, k_scale, k_shape, "[Attn] k")
    input_errors += _validate_nvfp4_input(v_quant, v_scale, v_shape, "[Attn] v")
    if input_errors:
        return False, "\n  ".join(input_errors)

    _seed_everything(_case_random_seed("attn", idx))
    start = time.perf_counter()
    try:
        result = hif4_quantize_attn(
            q_quant, q_scale,
            k_quant, k_scale,
            v_quant, v_scale,
        )
    except KeyboardInterrupt:
        raise
    except BaseException:
        return False, traceback.format_exc()
    runtime_ms = (time.perf_counter() - start) * 1000

    errors = validate_attn_result(result, q_shape, k_shape, v_shape)
    if errors:
        return False, f"quantize={runtime_ms:.2f}ms\n " + "\n  ".join(errors)

    return True, f"quantize={runtime_ms:.2f}ms"


def _load_solution_module(solution_dir: str):
    old_path = sys.path.copy()
    solution_dir = os.path.abspath(solution_dir)
    sys.path.insert(0, solution_dir)
    sys.modules.pop("solution", None)
    try:
        return importlib.import_module("solution")
    finally:
        sys.path = old_path


def _run_track(
    track_name: str,
    cases: Iterable[dict[str, Any]],
    checker: Callable[[Callable[..., Any], dict[str, Any], int], tuple[bool, str]],
    contestant_func: Callable[..., Any],
) -> CheckSummary:
    summary = CheckSummary()
    errors_summary: list[str] = []

    for idx, group in enumerate(cases):
        ok, detail = checker(contestant_func, group, idx)
        summary.add(ok)
        if ok:
            print(f"[{track_name}] Case {idx}: PASSED  ({detail})")
        else:
            errors_summary.append(f"Case {idx}: FAILED\n {detail}")
            print(f"[{track_name}] Case {idx}: FAILED\n {detail}")

    print(f"\n{'=' * 50} {track_name} Summary {'=' * 50}")
    print(f" Passed: {summary.passed}/{summary.total}")
    print(f" Failed: {summary.failed}/{summary.total}")
    if errors_summary:
        print("\n Error details:")
        for item in errors_summary:
            print(f"     {item}")
    return summary

def self_check(solution_dir: str, datasets_dir: str = DEFAULT_DATASETS_DIR) -> bool:
    solution_dir = os.path.abspath(solution_dir)
    datasets_dir = os.path.abspath(datasets_dir)
    solution_path = os.path.join(solution_dir, "solution.py")

    if not os.path.isfile(solution_path):
        print(f"Error: solution.py not found at {solution_path}")
        return False
    
    print(f"Loading solution from: {solution_dir}")
    try:
        module = _load_solution_module(solution_dir)
    except KeyboardInterrupt:
        raise
    except BaseException:
        print("Error: failed to import solution.py")
        traceback.print_exc()
        return False

    hif4_quantize = getattr(module, "hif4_quantize", None)
    hif4_quantize_attn = getattr(module, "hif4_quantize_attn", None)
    load_errors = []
    if not callable(hif4_quantize):
        load_errors.append("solution.hif4_quantize is missing or not callable")
    if not callable(hif4_quantize_attn):
        load_errors.append("solution.hif4_quantize_attn is missing or not callable")
    if load_errors:
        for error in load_errors:
            print(f"Error: {error}")
        return False

    linear_path = os.path.join(datasets_dir, "linear.pt")
    attn_path = os.path.join(datasets_dir, "attn.pt")
    missing_data = [path for path in (linear_path, attn_path) if not os.path.isfile(path)]
    if missing_data:
        for path in missing_data:
            print(f"Error: self-check data not found: {path}")
        return False

    try:
        linear_data = torch.load(linear_path, weights_only = True, map_location = 'cpu')
        attn_data = torch.load(attn_path, weights_only = True, map_location = 'cpu')
    except Exception:
        print("Error: failed to load self-check data")
        traceback.print_exc()
        return False

    

    overall = CheckSummary()

    print(f"\n{'=' * 50} Linear Track {'=' * 50}")
    overall.merge(_run_track("Linear", linear_data, check_linear_case, hif4_quantize))

    print(f"\n{'=' * 50} Attn Track {'=' * 50}")
    overall.merge(_run_track("Attn", attn_data, check_attn_case, hif4_quantize_attn))

    print(f"\n{'=' * 50} Overall {'=' * 50}")
    print(f"  Total passed: {overall.passed}/{overall.total}")
    print(f"  Total failed: {overall.failed}/{overall.total}")

    success = overall.total > 0 and overall.failed == 0
    if success:
        print("  ALL HIF4 FORMAT VALIDATIONS PASSED!")
    else:
        print("  SOME HIF4 FORMAT  VALIDATIONS FAILED - see details above")
    return success

def main() -> int:
    parser = argparse.ArgumentParser(description="HIF4 Match V2 V5-format self-check")
    parser.add_argument(
        "--solution_dir",
        type=str,
        required=True,
        help="Directory containing solution.py",
    )
    parser.add_argument(
        "--datasets_dir",
        type=str,
        default=DEFAULT_DATASETS_DIR,
        help="Directory containing linear.pt and attn.pt",
    )
    args = parser.parse_args()
    return 0 if self_check(args.solution_dir, args.datasets_dir) else 1


if __name__ == "__main__":
    raise SystemExit(main())