"""K8sFeatureChangeAnalysis — Kubernetes 特性变更 (Feature Changes) xlsx 自动生成。"""
from .parser import parse_go_file
from .analyzer import analyze
from .generator import generate_workbook

__all__ = ["parse_go_file", "analyze", "generate_workbook"]
