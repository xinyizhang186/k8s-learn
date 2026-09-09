"""parser.py — 解析 Kubernetes kube_features.go, 提取特性门的版本化规格.

输入: kube_features.go 文件路径 (如 v1.34.0kube_features.go)
输出: dict[bare_name -> FeatureGate]

FeatureGate 字段:
  key       : go map 键的末段 (去掉包前缀, 如 genericfeatures.Foo -> Foo)
  name      : 实际 feature gate 字符串值；与标识符不同时以此为展示名
  kep       : 从 const 块注释提取的 KEP 链接 (如 https://kep.k8s.io/3329)
  desc      : const 块描述行列表 (备用, 排查方法兜底)
  specs     : list[Spec], 按版本 (major, minor) 升序
  Spec      : dict(version:str, default:bool, stage:str, lock:bool, inline:str)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


class ParseError(Exception):
    """go 文件结构不符合预期 (缺少 const 块或 spec map)。"""


class FeatureGateMap(dict):
    """Mapping keyed by configured gate values with read-only Go-name aliases.

    Kubernetes occasionally changes only the capitalization of a Go
    identifier.  Analysis still sees one configured gate, while callers that
    have the identifier from the source can resolve it through ``get``.
    """

    def __init__(self):
        super().__init__()
        self._aliases: dict[str, str] = {}

    def get(self, key, default=None):
        return super().get(self._aliases.get(key, key), default)


@dataclass
class Spec:
    version: str
    default: bool
    stage: str
    lock: Optional[bool] = None
    inline: str = ""


@dataclass
class FeatureGate:
    name: str
    kep: Optional[str] = None
    desc: list[str] = field(default_factory=list)
    specs: list[Spec] = field(default_factory=list)


def _vt(v: str) -> tuple[int, int]:
    parts = v.split(".")
    return (int(parts[0]), int(parts[1]))


def _extract_kep(comment: str) -> Optional[str]:
    m = re.search(r'(https?://kep\.k8s\.io/\d+)', comment)
    return m.group(1) if m else None


def _find_block(src: str, start_marker: str) -> str:
    """定位 `start_marker` 起的代码块, 用括号匹配截取到匹配的 `)` 或 `}`。

    比 src.index + 正则更稳健: 不依赖固定缩进/换行格式。
    缺失 marker 抛 ParseError。
    """
    sm = re.search(re.escape(start_marker), src)
    if not sm:
        raise ParseError(f"未找到标记 {start_marker!r}")
    open_ch = "{" if start_marker.startswith("var") else "("
    close_ch = "}" if open_ch == "{" else ")"
    open_idx = src.find(open_ch, sm.start())
    if open_idx < 0:
        raise ParseError(f"未找到 {start_marker!r} 的起始括号")
    depth = 0
    for i in range(open_idx, len(src)):
        c = src[i]
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return src[open_idx:i + 1]
    raise ParseError(f"{start_marker!r} 块括号未闭合")


def _parse_const_block(block: str) -> dict[str, dict]:
    """解析 const 块, 返回 {字符串值: {kep, desc}}。

    同时记录 Go 标识符 -> 字符串值的映射, 供 spec map 的 bare name 对齐
    (解决标识符与字符串值大小写不一致导致 kep/desc 丢失的问题)。
    """
    feat_meta: dict[str, dict] = {}
    ident_to_val: dict[str, str] = {}
    decl_re = re.compile(
        r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s+(?:featuregate\.Feature\s*=\s*"([^"]+)"|=\s*featuregate\.Feature\("([^"]+)"\))'
    )
    pending: list[str] = []
    for line in block.splitlines():
        if line.strip().startswith("//"):
            pending.append(line)
            continue
        mm = decl_re.match(line)
        if mm and (mm.group(2) or mm.group(3)):
            val = mm.group(2) or mm.group(3)
            ident = mm.group(1)
            comment = "\n".join(pending) + ("\n" if pending else "")
            desc_lines: list[str] = []
            for cl in pending:
                s = cl.strip()
                if not s.startswith("//"):
                    continue
                s = s[2:].strip()
                if s.lower().startswith("owner:") or s.lower().startswith("kep:"):
                    continue
                if s:
                    desc_lines.append(s)
            feat_meta[val] = {"kep": _extract_kep(comment), "desc": desc_lines}
            ident_to_val[ident] = val
            pending = []
        else:
            pending = []
    return feat_meta, ident_to_val


def _split_spec_items(body: str) -> list[str]:
    r"""用括号深度切分 spec map body 为各 spec item 字符串。

    替代旧的 item_re=`\{([^{}]*)\}`: 该正则不支持嵌套大括号,
    若未来 go 结构体出现嵌套字面量会错位。栈匹配更稳健。
    """
    items: list[str] = []
    i = 0
    n = len(body)
    while i < n:
        if body[i] == "{":
            depth = 0
            start = i
            while i < n:
                if body[i] == "{":
                    depth += 1
                elif body[i] == "}":
                    depth -= 1
                    if depth == 0:
                        items.append(body[start + 1:i])
                        i += 1
                        break
                i += 1
        else:
            i += 1
    return items


def parse_item(s: str) -> Optional[Spec]:
    """从单个 spec item 文本提取 Spec (各字段独立搜索, 顺序无关)。"""
    vm = re.search(r'Version:\s*version\.MustParse\("([^"]+)"\)', s)
    dm = re.search(r'Default:\s*(true|false)', s)
    pm = re.search(r'PreRelease:\s*featuregate\.(\w+)', s)
    if not (vm and dm and pm):
        return None
    lm = re.search(r'LockToDefault:\s*(true|false)', s)
    cmnt = re.search(r'//\s*(.*)$', s)
    return Spec(
        version=vm.group(1),
        default=(dm.group(1) == "true"),
        stage=pm.group(1),
        lock=((lm.group(1) == "true") if lm else None),
        inline=(cmnt.group(1).strip() if cmnt else ""),
    )


def parse_go_file(path: str | Path) -> dict[str, FeatureGate]:
    src = Path(path).read_text(encoding="utf-8")

    const_block = _find_block(src, "const (")
    feat_meta, ident_to_val = _parse_const_block(const_block)

    spec_block = _find_block(src, "var defaultVersionedKubernetesFeatureGates")

    # 每个 gate 条目: `Name: { {...}, {...} }` — 用括号匹配切出
    gates = FeatureGateMap()
    i = 0
    n = len(spec_block)
    while i < n:
        m = re.match(r'\s*([A-Za-z_][A-Za-z0-9_.]*)\s*:\s*\{', spec_block[i:])
        if not m:
            i += 1
            continue
        bare = m.group(1).strip().split(".")[-1]
        body_start = i + m.end() - 1  # 指向 `{`
        depth = 0
        j = body_start
        body = ""
        while j < n:
            if spec_block[j] == "{":
                depth += 1
            elif spec_block[j] == "}":
                depth -= 1
                if depth == 0:
                    body = spec_block[body_start + 1:j]
                    break
            j += 1
        if not body:
            i += m.end()
            continue

        specs: list[Spec] = []
        for item_text in _split_spec_items(body):
            sp = parse_item(item_text)
            if sp is not None:
                specs.append(sp)
        if not specs:
            i = j + 1
            continue
        specs.sort(key=lambda e: _vt(e.version))

        # 元数据对齐: 优先用标识符查 ident_to_val, 再用字符串值查 feat_meta;
        # 解决大小写不一致 (如 RuntimeClassInImageCriAPI vs "RuntimeClassInImageCriApi")
        val = ident_to_val.get(bare, bare)
        meta = feat_meta.get(val) or feat_meta.get(bare, {})
        # Kubernetes users configure the string value, not the Go identifier.
        # For example CPUCFSQuotaPeriod is declared as
        # `CPUCFSQuotaPeriod featuregate.Feature = "CustomCPUCFSQuotaPeriod"`.
        # The output must therefore use the value seen in configuration.
        gates[val] = FeatureGate(
            name=val,
            kep=meta.get("kep"),
            desc=meta.get("desc", []),
            specs=specs,
        )
        if bare != val:
            gates._aliases[bare] = val
        i = j + 1
    return gates
