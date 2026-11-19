"""Generate EX002 stress-test figures from measured JSON."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
FIG = ROOT / "docs" / "results" / "figures" / "ex002"
FIG.mkdir(parents=True, exist_ok=True)
S = json.loads(
    (ROOT / "outputs" / "ex002" / "summary.json").read_text(encoding="utf-8")
)

C = {
    "red": "#D32F2F",
    "blue": "#1976D2",
    "orange": "#EF6C00",
    "green": "#2E7D32",
    "purple": "#6A1B9A",
}


def save(fig, name):
    path = FIG / name
    plt.tight_layout()
    plt.savefig(
        path,
        dpi=150,
        bbox_inches="tight",
        facecolor="white",
        pil_kwargs={"optimize": True},
    )
    plt.close()
    print(path, path.stat().st_size)


def fig_e1():
    fig, ax = plt.subplots(figsize=(7.2, 4.2), dpi=150)
    for key, color, marker in (
        ("selector", C["red"], "o"),
        ("semantic", C["blue"], "s"),
    ):
        rows = S["E1_interface"][key]
        ax.plot(
            [r["perturb_prob"] for r in rows],
            [r["success_rate"] * 100 for r in rows],
            color=color,
            marker=marker,
            linewidth=2.4,
            markersize=8,
            label=key,
        )
        for r in rows:
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
    ax.set_title("EX002 E1: semantic interface under DOM churn")
    ax.set_ylim(-5, 108)
    ax.grid(linestyle="--", alpha=0.3)
    ax.legend()
    save(fig, "e1_interface.png")


def fig_e2():
    d = S["E2_hierarchy"]
    fig, ax = plt.subplots(figsize=(6.4, 4.2), dpi=150)
    vals = [d["flat_success_rate"] * 100, d["hierarchy_success_rate"] * 100]
    bars = ax.bar(
        ["flat router", "hierarchy"], vals, color=[C["orange"], C["green"]], width=0.55
    )
    for b, v in zip(bars, vals):
        ax.text(
            b.get_x() + b.get_width() / 2, v + 2, f"{v:.1f}%", ha="center", fontsize=10
        )
    ax.set_ylim(0, 108)
    ax.set_ylabel("Success rate (%)")
    ax.set_title("EX002 E2: flat routing vs hierarchy (9 real tasks)")
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    save(fig, "e2_hierarchy.png")


def fig_e3():
    d = S["E3_verifier_hints"]
    fig, ax = plt.subplots(figsize=(6.4, 4.2), dpi=150)
    vals = [d["off_success_rate"] * 100, d["on_success_rate"] * 100]
    bars = ax.bar(
        ["no phi/missing", "with phi/missing"],
        vals,
        color=[C["red"], C["green"]],
        width=0.55,
    )
    for b, v in zip(bars, vals):
        ax.text(
            b.get_x() + b.get_width() / 2, v + 2, f"{v:.1f}%", ha="center", fontsize=10
        )
    ax.set_ylim(0, 108)
    ax.set_ylabel("Success rate (%)")
    ax.set_title("EX002 E3: verifier-aware observation ablation")
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    save(fig, "e3_verifier.png")


def fig_e4():
    d = S["E4_layout_adaptive"]
    fig, ax = plt.subplots(figsize=(7.2, 4.2), dpi=150)
    labels = ["v1/v2 30 tasks", "v3 fixed", "v3 LASC"]
    vals = [
        d["v1v2_30_scenarios_success"] * 100,
        d["v3_baseline_success"] / d["v3_baseline_tasks"] * 100,
        d["v3_lasc_success"] / d["v3_lasc_tasks"] * 100,
    ]
    bars = ax.bar(labels, vals, color=[C["blue"], C["red"], C["green"]], width=0.55)
    for b, v in zip(bars, vals):
        ax.text(
            b.get_x() + b.get_width() / 2, v + 2, f"{v:.1f}%", ha="center", fontsize=10
        )
    ax.set_ylim(0, 108)
    ax.set_ylabel("Success rate (%)")
    ax.set_title("EX002 E4: layout/control heterogeneity")
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    save(fig, "e4_layout.png")


def fig_e5():
    d = S["E5_observation"]
    fig, ax = plt.subplots(figsize=(7.2, 4.2), dpi=150)
    labels = ["calls", "browser roundtrips", "observe seconds"]
    base = [d["baseline_calls"], d["baseline_roundtrips"], d["baseline_seconds"]]
    new = [d["ar025_calls"], d["ar025_roundtrips"], d["ar025_seconds"]]
    x = np.arange(len(labels))
    w = 0.36
    ax.bar(x - w / 2, base, w, color=C["red"], label="pre-AR025")
    ax.bar(x + w / 2, new, w, color=C["green"], label="AR025 AOC")
    for i, (b, n) in enumerate(zip(base, new)):
        ax.text(i + w / 2, n + max(base) * 0.01, f"{n:g}", ha="center", fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_title("EX002 E5: observation overhead (30 real scenarios)")
    ax.set_ylabel("count / seconds")
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    ax.legend()
    save(fig, "e5_observation.png")


def fig_e6():
    d = S["E7_fault_long_chain"]
    fig, ax = plt.subplots(figsize=(7.6, 4.2), dpi=150)
    groups = [
        ("AR016\nmulti-order", d["AR016"]),
        ("AR017\nSaga", d["AR017"]),
        ("AR018\nretry", d["AR018"]),
    ]
    labels, base, new = [], [], []
    for label, modes in groups:
        labels.append(label)
        base_mode = next(
            k for k in modes if k in ("merged_llm", "no_compensation", "single_attempt")
        )
        new_mode = next(k for k in modes if k not in (base_mode,))
        base.append(modes[base_mode]["success"])
        new.append(modes[new_mode]["success"])
    x = np.arange(len(labels))
    w = 0.36
    ax.bar(x - w / 2, base, w, color=C["red"], label="baseline")
    ax.bar(x + w / 2, new, w, color=C["green"], label="composed")
    for i, (b, n) in enumerate(zip(base, new)):
        ax.text(i - w / 2, b + 0.05, str(b), ha="center")
        ax.text(i + w / 2, n + 0.05, str(n), ha="center")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylim(0, max(base + new) + 1)
    ax.set_ylabel("successful tasks")
    ax.set_title("EX002 E6: fault/long-chain stress")
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    ax.legend()
    save(fig, "e6_faults.png")


if __name__ == "__main__":
    fig_e1()
    fig_e2()
    fig_e3()
    fig_e4()
    fig_e5()
    fig_e6()
