#!/usr/bin/env python3
"""AutoK8s — Kubernetes 版本分析与特性变更统一入口。

自适应模式:
  仅 --blog URL        → 版本分析 (单 Sheet)
  仅 --go-file + range → 特性变更 (单 Sheet)
  两者都给             → 双 Sheet 合并工作簿

示例:
  # 版本分析
  python generate.py --blog https://kubernetes.io/blog/2026/04/22/kubernetes-v1-36-release/

  # 特性变更
  python generate.py --go-file data/v1.36.0kube_features.go --range 1.35 1.36

  # 双 Sheet 合并
  python generate.py \
      --blog https://kubernetes.io/blog/2026/04/22/kubernetes-v1-36-release/ \
             https://kubernetes.io/blog/2025/11/26/kubernetes-v1-35-sneak-peek/ \
             https://kubernetes.io/blog/2025/08/27/kubernetes-v1-34-release/ \
      --go-file data/v1.36.0kube_features.go --range 1.35 1.36 \
      --output output/v1.35-v1.36/k8sv1.35-v1.36.xlsx
"""
from __future__ import annotations

from autok8s.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
