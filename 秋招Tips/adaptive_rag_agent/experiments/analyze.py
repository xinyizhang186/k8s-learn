"""Analyze experiment results: generate comparison charts + summary tables."""
from __future__ import annotations

import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

MODES_ORDER = ["naive", "hybrid", "agentic"]
COLORS = {"naive": "#e74c3c", "hybrid": "#3498db", "agentic": "#2ecc71"}
METRICS = ["em", "f1", "ctx_recall", "ctx_p@2", "ctx_p@4"]


def _ordered_modes(summary):
    return [m for m in MODES_ORDER if m in summary]


def main(path: str = "results/exp_full.json") -> None:
    d = json.load(open(path, encoding="utf-8"))
    summary = d["summary"]
    by_type = d.get("by_type", {})
    per_q = d.get("per_question", [])
    modes = _ordered_modes(summary)
    os.makedirs("results", exist_ok=True)

    # ---- fig 1: overall metrics ----------------------------------------
    fig, axes = plt.subplots(1, len(METRICS), figsize=(20, 4))
    for ax, m in zip(axes, METRICS):
        vals = [summary[mo].get(m, 0) for mo in modes]
        bars = ax.bar(modes, vals, color=[COLORS[mo] for mo in modes])
        ax.set_title(m.upper(), fontsize=13, fontweight="bold")
        ax.set_ylim(0, max(0.1, max(vals) * 1.25))
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v, f"{v:.3f}",
                    ha="center", va="bottom", fontsize=9)
    fig.suptitle(f"Overall Retrieval & Answer Metrics  (n={d['n']})",
                 fontsize=14, fontweight="bold")
    plt.tight_layout()
    plt.savefig("results/overall_comparison.png", dpi=120, bbox_inches="tight")
    plt.close()

    # ---- fig 2: by question type ---------------------------------------
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    x = np.arange(len(METRICS))
    w = 0.25
    for ax, ty in zip(axes, ["bridge", "comparison"]):
        for i, mo in enumerate(modes):
            vals = [by_type.get(mo, {}).get(ty, {}).get(m, 0) for m in METRICS]
            ax.bar(x + i * w, vals, w, label=mo, color=COLORS[mo])
        ax.set_xticks(x + w)
        ax.set_xticklabels([m.upper() for m in METRICS])
        ax.set_title(f"{ty} questions", fontweight="bold")
        ax.set_ylim(0, 1.0)
        ax.legend()
    fig.suptitle("Performance by Question Type", fontsize=14, fontweight="bold")
    plt.tight_layout()
    plt.savefig("results/by_type_comparison.png", dpi=120, bbox_inches="tight")
    plt.close()

    # ---- fig 3: agent rounds + latency ----------------------------------
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    if "agentic" in summary and per_q:
        rounds = [r["agentic"]["rounds"] for r in per_q if "agentic" in r]
        if rounds:
            axes[0].hist(rounds, bins=range(1, max(rounds) + 2),
                         color=COLORS["agentic"], edgecolor="black",
                         align="left", rwidth=0.8)
            axes[0].set_title("Agentic: retrieval-rounds distribution")
            axes[0].set_xlabel("rounds"); axes[0].set_ylabel("count")
    lats = [summary[mo].get("latency", 0) for mo in modes]
    bars = axes[1].bar(modes, lats, color=[COLORS[mo] for mo in modes])
    axes[1].set_title("Avg latency per question (s)")
    for b, v in zip(bars, lats):
        axes[1].text(b.get_x() + b.get_width() / 2, v, f"{v:.2f}s",
                     ha="center", va="bottom")
    fig.suptitle("Agent Behavior & Efficiency", fontsize=14, fontweight="bold")
    plt.tight_layout()
    plt.savefig("results/agent_analysis.png", dpi=120, bbox_inches="tight")
    plt.close()

    # ---- markdown tables ------------------------------------------------
    print(f"## Overall Results (n={d['n']})\n")
    print("| Metric | " + " | ".join(modes) + " |")
    print("|" + "---|" * (len(modes) + 1))
    for m in METRICS + ["avg_rounds", "latency"]:
        print(f"| {m} | " + " | ".join(f"{summary[mo].get(m,0):.4f}" for mo in modes) + " |")

    if "agentic" in summary and "hybrid" in summary:
        print("\n## Agentic vs Hybrid (the core contribution)\n")
        for m in METRICS:
            h = summary["hybrid"].get(m, 0)
            a = summary["agentic"].get(m, 0)
            delta = a - h
            pct = (delta / h * 100) if h > 0 else float("inf")
            arrow = "↑" if delta >= 0 else "↓"
            print(f"- **{m.upper()}**: {h:.4f} → {a:.4f}  ({arrow}{abs(pct):.1f}%)")

    print("\n## By Type\n")
    for ty in ["bridge", "comparison"]:
        print(f"### {ty}\n")
        print("| Metric | " + " | ".join(modes) + " |")
        print("|" + "---|" * (len(modes) + 1))
        for m in METRICS + ["avg_rounds"]:
            print(f"| {m} | " + " | ".join(
                f"{by_type.get(mo,{}).get(ty,{}).get(m,0):.4f}" for mo in modes) + " |")

    print("\nCharts: overall_comparison.png, by_type_comparison.png, agent_analysis.png")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "results/exp_full.json")
