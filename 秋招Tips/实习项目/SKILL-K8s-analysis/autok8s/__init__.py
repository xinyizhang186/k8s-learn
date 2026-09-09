"""AutoK8s — Kubernetes 版本分析与特性变更合并工具包。

统一入口 detect 输入类型自适应选择分析:
  - --blog URL       → 版本分析 (版本分析 sheet)
  - --go-file + range → 特性变更 (特性变更 sheet)
  - 两者都给          → 双 Sheet 合并工作簿
"""
