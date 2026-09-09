"""K8sVersionAnalysis — Kubernetes 版本分析 xlsx 自动生成。"""
from .fetcher import fetch_release_blog
from .content_gen import generate_analysis
from .xlsx_writer import write_workbook

__all__ = ["fetch_release_blog", "generate_analysis", "write_workbook"]
