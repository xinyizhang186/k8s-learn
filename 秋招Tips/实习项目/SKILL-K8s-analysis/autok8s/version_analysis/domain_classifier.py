"""domain_classifier.py — 特性价值领域分类 (从 content_gen.py 抽出)。"""
from __future__ import annotations


_KEYWORDS = {
    "功能：API": ["api", "admission", "validation", "CRD", "custom resource", "webhook", "schema", "kubectl", "kuberc", "config", "manifest", "deployment", "statefulset", "job"],
    "功能：Node": ["kubelet", "node", "pod", "container", "cgroup", "runtime", "CRI", "PSI", "NUMA", "topology", "restart", "lifecycle"],
    "功能：存储": ["volume", "CSI", "snapshot", "PVC", "PV", "storage", "SELinux", "OCI artifact", "image volume", "attach", "mount"],
    "功能：调度": ["scheduler", "scheduling", "DRA", "resource", "gang", "batch", "workload aware", "placement", "toleration"],
    "功能：扩缩容": ["HPA", "autoscal", "scale", "replica"],
    "功能：网络": ["network", "service", "ingress", "CIDR", "IP", "proxy", "route", "traffic", "kube-proxy", "DNS", "CCM"],
    "功能：运维": ["log", "debug", "statusz", "flagz", "kuberc", "YAML", "KYAML", "configuration", "kubectl", "preference"],
    "DFX:安全": ["auth", "RBAC", "security", "token", "service account", "impersonat", "certificate", "namespace", "SELinux", "gogoprotobuf", "credential", "user namespace"],
    "DFX:可靠": ["reliab", "stale", "consistency", "version", "migration", "upgrade", "proxy", "mixed version"],
    "DFX:性能": ["performance", "memory", "latency", "streaming", "batch", "histogram", "metric", "QoS", "pressure"],
    "DFX:运维": ["observab", "monitor", "debug", "statusz", "flagz", "log", "trace", "component"],
}


def classify_domain(text: str) -> str:
    lower = text.lower()
    scores: dict[str, int] = {}
    for domain, keywords in _KEYWORDS.items():
        score = sum(1 for kw in keywords if kw.lower() in lower)
        if score > 0:
            scores[domain] = score
    if scores:
        return max(scores, key=scores.get)
    return "功能：API"
