"""Run the full AR001 evaluation matrix on all held-out tasks."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from step_rl.edge.evaluate import run_matrix  # noqa: E402

CONFIGS = [
    {"label": "sft", "adapter": "outputs/ar001/sft_adapter", "repair": False},
    {"label": "sft_repair", "adapter": "outputs/ar001/sft_adapter", "repair": True},
    {
        "label": "sparse_grpo_repair",
        "adapter": "outputs/ar001/grpo_sparse",
        "repair": True,
    },
    {
        "label": "vgdp_grpo_repair",
        "adapter": "outputs/ar001/grpo_vgdp",
        "repair": True,
    },
]


def main() -> None:
    report = asyncio.run(run_matrix(CONFIGS, "outputs/ar001/eval", max_steps=8))
    print(json.dumps(report["best"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
