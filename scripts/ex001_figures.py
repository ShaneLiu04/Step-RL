"""Generate EX001 interpretability figures from measured JSON."""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs" / "ex001"
FIG = ROOT / "docs" / "results" / "figures" / "ex001"
FIG.mkdir(parents=True, exist_ok=True)

COLORS = {
    "selector": "#D32F2F",
    "semantic": "#1976D2",
    "flat": "#FF9800",
    "hierarchy": "#2E7D32",
    "off": "#D32F2F",
    "on": "#2E7D32",
}


def load(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def fig_e1():
    rows = load("outputs/ex001/e1_perturb.json")
    fig, ax = plt.subplots(figsize=(7.2, 4.2), dpi=150)
    for interface, color, marker in (
        ("selector", COLORS["selector"], "o"),
        ("semantic", COLORS["semantic"], "s"),
    ):
        items = sorted(
            [r for r in rows if r["interface"] == interface],
            key=lambda r: r["perturb_prob"],
        )
        ax.plot(
            [r["perturb_prob"] for r in items],
            [r["success_rate"] * 100 for r in items],
            color=color,
            marker=marker,
            linewidth=2.4,
            markersize=8,
            label=interface,
        )
        for r in items:
            ax.annotate(
                f"{r['raw_invalid']} inv",
                (r["perturb_prob"], r["success_rate"] * 100),
                textcoords="offset points",
                xytext=(0, 9),
                ha="center",
                fontsize=7,
                color=color,
            )
    ax.set_xlabel("Probability of DOM id churn after observation")
    ax.set_ylabel("Success rate (%)")
    ax.set_title("E1: Action interface robustness under DOM churn")
    ax.set_ylim(-5, 108)
    ax.grid(linestyle="--", alpha=0.3)
    ax.legend()
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()
    path = FIG / "e1_perturbation.png"
    plt.savefig(
        path,
        dpi=150,
        bbox_inches="tight",
        facecolor="white",
        pil_kwargs={"optimize": True},
    )
    plt.close()
    print(path, path.stat().st_size)


def per_level(data):
    agg = defaultdict(lambda: [0, 0])
    for item in data["results"]:
        agg[item["level"]][1] += 1
        agg[item["level"]][0] += int(item["success"])
    return {level: 100 * ok / total for level, (ok, total) in sorted(agg.items())}


def fig_e2():
    flat = load("outputs/ex001/e2_flat.json")
    hierarchy = load("outputs/ar004/eval/semantic_stable.json")
    levels = sorted(per_level(hierarchy))
    flat_values = [per_level(flat).get(level, 0) for level in levels]
    hier_values = [per_level(hierarchy).get(level, 0) for level in levels]
    x = np.arange(len(levels))
    width = 0.36
    fig, ax = plt.subplots(figsize=(7.2, 4.2), dpi=150)
    ax.bar(x - width / 2, flat_values, width, color=COLORS["flat"], label="flat router")
    ax.bar(
        x + width / 2, hier_values, width, color=COLORS["hierarchy"], label="hierarchy"
    )
    ax.set_xticks(x)
    ax.set_xticklabels([f"L{level}" for level in levels])
    ax.set_ylim(0, 108)
    ax.set_ylabel("Success rate (%)")
    ax.set_title("E2: Flat routing vs hierarchical decomposition")
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    ax.legend()
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()
    path = FIG / "e2_hierarchy.png"
    plt.savefig(
        path,
        dpi=150,
        bbox_inches="tight",
        facecolor="white",
        pil_kwargs={"optimize": True},
    )
    plt.close()
    print(path, path.stat().st_size)


def fig_e3():
    off = load("outputs/ex001/e3_hints_off.json")
    on = load("outputs/ar004/eval/semantic_stable.json")
    levels = sorted(per_level(on))
    off_values = [per_level(off).get(level, 0) for level in levels]
    on_values = [per_level(on).get(level, 0) for level in levels]
    x = np.arange(len(levels))
    width = 0.36
    fig, ax = plt.subplots(figsize=(7.2, 4.2), dpi=150)
    ax.bar(
        x - width / 2, off_values, width, color=COLORS["off"], label="no phi/missing"
    )
    ax.bar(
        x + width / 2, on_values, width, color=COLORS["on"], label="with phi/missing"
    )
    ax.set_xticks(x)
    ax.set_xticklabels([f"L{level}" for level in levels])
    ax.set_ylim(0, 108)
    ax.set_ylabel("Success rate (%)")
    ax.set_title("E3: Verifier-aware observation ablation")
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    ax.legend()
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()
    path = FIG / "e3_hints.png"
    plt.savefig(
        path,
        dpi=150,
        bbox_inches="tight",
        facecolor="white",
        pil_kwargs={"optimize": True},
    )
    plt.close()
    print(path, path.stat().st_size)


def fig_e6():
    rows = load("outputs/ex001/e6_failures.json")
    wanted = [
        "AR001 SFT",
        "AR001 VGDP",
        "AR001 router",
        "AR005 selector v2 churn",
        "AR006 naive",
    ]
    selected = [r for r in rows if r["condition"] in wanted]
    stages = [
        "search/navigation",
        "product/cart",
        "checkout/form",
        "order/final",
        "planning/constraint",
    ]
    colors = ["#B71C1C", "#EF6C00", "#F9A825", "#1565C0", "#6A1B9A"]
    fig, ax = plt.subplots(figsize=(8.2, 4.0), dpi=150)
    y = np.arange(len(selected))
    left = np.zeros(len(selected))
    for stage, color in zip(stages, colors):
        values = np.array([r["failure_stages"][stage] for r in selected])
        ax.barh(y, values, left=left, color=color, label=stage)
        left += values
    ax.set_yticks(y)
    ax.set_yticklabels([r["condition"] for r in selected], fontsize=8)
    ax.set_xlabel("Failure count")
    ax.set_title("E6: Where failures occur (real held-out episodes)")
    ax.legend(fontsize=7, ncol=3, loc="lower right")
    ax.invert_yaxis()
    ax.grid(axis="x", linestyle="--", alpha=0.3)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()
    path = FIG / "e6_failure_taxonomy.png"
    plt.savefig(
        path,
        dpi=150,
        bbox_inches="tight",
        facecolor="white",
        pil_kwargs={"optimize": True},
    )
    plt.close()
    print(path, path.stat().st_size)


def fig_e7():
    data = load("outputs/ex001/e7_stability.json")["per_task"]
    tasks = list(data)
    steps = [data[t]["avg_steps"] for t in tasks]
    tokens = [data[t]["tokens_per_success"] for t in tasks]
    fig, axes = plt.subplots(1, 2, figsize=(9.0, 3.8), dpi=150)
    axes[0].bar(tasks, steps, color="#1976D2")
    axes[0].set_title("Average steps")
    axes[0].set_ylabel("steps")
    axes[0].tick_params(axis="x", rotation=15)
    axes[1].bar(tasks, tokens, color="#7B1FA2")
    axes[1].set_title("Tokens per successful task")
    axes[1].set_ylabel("tokens")
    axes[1].tick_params(axis="x", rotation=15)
    for ax in axes:
        ax.grid(axis="y", linestyle="--", alpha=0.3)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
    fig.suptitle(
        "E7: Repeatability and cost (2 repeats, all 100% success)", fontsize=11
    )
    plt.tight_layout(rect=[0, 0, 1, 0.94])
    path = FIG / "e7_cost.png"
    plt.savefig(
        path,
        dpi=150,
        bbox_inches="tight",
        facecolor="white",
        pil_kwargs={"optimize": True},
    )
    plt.close()
    print(path, path.stat().st_size)


def fig_e8():
    data = load("outputs/ex001/e8_hardware.json")
    labels = ["planner\nCPU", "verifier\nCPU", "HTTP shop\nCPU", "LLM gen\nGPU"]
    values = [
        data["cpu"]["planner_p50_ms"],
        data["cpu"]["verifier_p50_ms"],
        data["cpu"]["http_p50_ms"],
        data["gpu"]["gen_p50_ms"],
    ]
    colors = ["#2E7D32", "#43A047", "#66BB6A", "#D32F2F"]
    fig, ax = plt.subplots(figsize=(7.0, 3.8), dpi=150)
    bars = ax.barh(labels, values, color=colors)
    ax.set_xscale("log")
    ax.set_xlabel("P50 latency (ms, log scale)")
    ax.set_title("E8: Where the end-side latency budget goes")
    for bar, value in zip(bars, values):
        ax.text(
            value * 1.15,
            bar.get_y() + bar.get_height() / 2,
            f"{value:.2f} ms",
            va="center",
            fontsize=8,
        )
    ax.grid(axis="x", linestyle="--", alpha=0.3)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()
    path = FIG / "e8_hardware.png"
    plt.savefig(
        path,
        dpi=150,
        bbox_inches="tight",
        facecolor="white",
        pil_kwargs={"optimize": True},
    )
    plt.close()
    print(path, path.stat().st_size)


if __name__ == "__main__":
    fig_e1()
    fig_e2()
    fig_e3()
    fig_e6()
    fig_e7()
    fig_e8()
