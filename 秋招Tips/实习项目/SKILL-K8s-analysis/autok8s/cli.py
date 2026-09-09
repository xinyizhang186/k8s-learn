"""cli.py — 自适应命令行入口。

根据传入参数自动选择分析模式:
  - 仅 --blog URL       → 版本分析 (单 Sheet "版本分析")
  - 仅 --go-file + range → 特性变更 (单 Sheet "特性变更")
  - 两者都给            → 双 Sheet 合并工作簿
  - 都不给              → 报错
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .version_analysis.fetcher import fetch_release_blog, _FETCH_RETRIES
from .version_analysis.content_gen import generate_analysis, generate_multi_version_analysis
from .version_analysis.xlsx_writer import write_workbook as write_version_workbook
from .feature_changes.generator import generate_workbook as generate_feature_changes
from .workbook import generate_combined_workbook


def _parse_version(s: str) -> tuple[int, int]:
    parts = s.strip().lstrip("v").split(".")
    if len(parts) < 2:
        raise ValueError(f"版本号格式错误, 应为 '1.34' 形式: {s!r}")
    return (int(parts[0]), int(parts[1]))


def _build_output_path(user_path: str | None, default_name: str, version_dir: str) -> Path:
    """构建输出路径: 默认放入 output/v{版本范围}/ 文件夹; 用户指定 --output 时直接使用。

    version_dir 为完整版本范围标识:
      - 单版本: 'v1.36'
      - 跨版本: 'v1.34-v1.36'
    """
    if user_path:
        p = Path(user_path)
    else:
        p = Path("output") / version_dir / default_name
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _version_str(ver: tuple[int, int]) -> str:
    return f"{ver[0]}.{ver[1]}"


def _version_dir(lo: tuple[int, int] | None = None, hi: tuple[int, int] | None = None,
                 blog_versions: list[str] | None = None) -> str:
    """生成版本范围文件夹名: 跨版本用 'v1.34-v1.36', 单版本用 'v1.36'。"""
    if blog_versions:
        versions = sorted(blog_versions)
        if len(versions) == 1:
            return f"v{versions[0]}"
        return f"v{versions[0]}-v{versions[-1]}"
    if lo and hi:
        if lo == hi:
            return f"v{_version_str(lo)}"
        return f"v{_version_str(lo)}-v{_version_str(hi)}"
    if hi:
        return f"v{_version_str(hi)}"
    return "output"


def _run_version_analysis(blog_urls: list[str], output: str | Path,
                          pre_fetched: list | None = None) -> int:
    all_blog_data = pre_fetched or []
    if not all_blog_data:
        for url in blog_urls:
            blog_data = fetch_release_blog(url)
            if not blog_data:
                print(f"错误: 无法抓取或解析博客页面 {url} (重试 {_FETCH_RETRIES} 次后仍失败)", file=sys.stderr)
                return 1
            all_blog_data.append(blog_data)

    all_blog_data.sort(key=lambda b: _parse_version(b.version), reverse=True)

    if len(all_blog_data) == 1:
        analysis = generate_analysis(all_blog_data[0])
    else:
        analysis = generate_multi_version_analysis(all_blog_data)

    write_version_workbook(analysis, str(output))
    print(f"已生成 {output} (版本分析 {len(analysis['features'])} 条特性, "
          f"{len(analysis.get('deprecations', []))} 条弃用)")
    return 0


def _run_feature_changes(
    go_file: str, lo: tuple[int, int], hi: tuple[int, int], output: str | Path,
    *, data_dir: str | Path | None = None, offline: bool = False, audit: str | Path | None = None,
) -> int:
    n = generate_feature_changes(
        go_file, str(output), lo=lo, hi=hi, data_dir=data_dir,
        offline=offline, audit_path=audit,
    )
    print(f"已生成 {output} (特性变更 {n} 条)")
    return 0


def _run_combined(
    blog_urls: list[str], go_file: str, lo: tuple[int, int], hi: tuple[int, int], output: str | Path,
    *, data_dir: str | Path | None = None, offline: bool = False, audit: str | Path | None = None,
) -> int:
    features, changes = generate_combined_workbook(
        blog_urls, go_file, lo, hi, output, data_dir=data_dir,
        offline=offline, audit_path=audit,
    )
    print(f"已生成 {output} (版本分析 {features} 条特性, 特性变更 {changes} 条)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="generate.py",
        description="Kubernetes 版本分析与特性变更工具 (自适应: 根据输入参数选择分析模式)",
    )
    parser.add_argument(
        "--blog", action="append", nargs="+", default=[], metavar="URL",
        help="官方 Kubernetes 发布博客 URL; 一次可传多个 URL，也可重复 --blog",
    )
    parser.add_argument("--go-file", default=None, metavar="PATH",
                        help="kube_features.go 文件路径 (启用特性变更)")
    parser.add_argument("--range", nargs=2, default=None, metavar=("LO", "HI"),
                        help="特性变更版本范围, 如 --range 1.35 1.37")
    parser.add_argument("--output", "-o", default=None, metavar="PATH",
                        help="输出 xlsx 路径 (默认: 自动命名)")
    parser.add_argument("--data-dir", default="data", metavar="PATH",
                        help="特性资料缓存目录（默认: data）")
    parser.add_argument("--offline", action="store_true",
                        help="特性变更分析不联网，仅使用 --data-dir 中的缓存和 CHANGELOG")
    parser.add_argument("--audit", default=None, metavar="PATH",
                        help="特性变更逐条核查 JSON 输出路径")

    args = parser.parse_args(argv)

    blog_urls = [url for group in args.blog for url in group]
    has_blog = bool(blog_urls)
    has_go = args.go_file is not None
    has_range = args.range is not None

    if not has_blog and not has_go:
        parser.error("至少需要 --blog 或 --go-file 之一")

    if has_go and not has_range:
        parser.error("--go-file 必须配合 --range 使用")
    if has_range and not has_go:
        parser.error("--range 必须配合 --go-file 使用")

    go_file = Path(args.go_file) if has_go else None
    if go_file and not go_file.is_file():
        parser.error(f"找不到 kube_features.go: {go_file}")

    lo = hi = None
    if has_range:
        lo = _parse_version(args.range[0])
        hi = _parse_version(args.range[1])
        if lo > hi:
            parser.error(f"--range 下界 {args.range[0]} 大于上界 {args.range[1]}")

    if has_blog and has_go:
        assert lo is not None and hi is not None
        vdir = _version_dir(lo, hi)
        output = _build_output_path(
            args.output, f"k8sv{_version_str(lo)}-v{_version_str(hi)}.xlsx", vdir,
        )
        return _run_combined(
            blog_urls, str(go_file), lo, hi, str(output), data_dir=args.data_dir,
            offline=args.offline, audit=args.audit,
        )

    if has_blog:
        pre_fetched = []
        for url in blog_urls:
            blog = fetch_release_blog(url)
            if not blog:
                print(f"错误: 无法抓取或解析博客页面 {url} (重试 {_FETCH_RETRIES} 次后仍失败)", file=sys.stderr)
                return 1
            pre_fetched.append(blog)

        blog_versions = [b.version for b in pre_fetched]
        vdir = _version_dir(blog_versions=blog_versions)
        if len(pre_fetched) == 1:
            default_name = f"k8s_v{pre_fetched[0].version}_release_analyse.xlsx"
        else:
            versions = sorted(blog_versions)
            default_name = f"k8s_v{versions[0]}-v{versions[-1]}_release_analyse.xlsx"
        output = _build_output_path(args.output, default_name, vdir)
        return _run_version_analysis(blog_urls, str(output), pre_fetched=pre_fetched)

    assert has_go and has_range and lo is not None and hi is not None
    vdir = _version_dir(hi=hi)
    output = _build_output_path(
        args.output, f"k8s{_version_str(lo)}-{_version_str(hi)}.xlsx", vdir,
    )
    return _run_feature_changes(
        str(go_file), lo, hi, str(output), data_dir=args.data_dir,
        offline=args.offline, audit=args.audit,
    )


if __name__ == "__main__":
    raise SystemExit(main())
