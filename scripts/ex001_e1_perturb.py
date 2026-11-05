"""E1: action interface vs DOM perturbation probability."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from step_rl.edge.evaluate import evaluate_policy  # noqa: E402
from step_rl.edge.tasks import EVAL_TASKS  # noqa: E402

OUT = ROOT / "outputs" / "ex001"
TASKS = EVAL_TASKS[:4]
PROBS = [0.0, 0.25, 0.5, 0.75, 1.0]


async def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for interface, adapter, semantic, repair in (
        ("selector", "outputs/ar001/sft_adapter", False, True),
        ("semantic", "outputs/ar004/sft_semantic", True, False),
    ):
        for prob in PROBS:
            summary = await evaluate_policy(
                f"{interface}_p{prob}",
                adapter,
                repair=repair,
                tasks=TASKS,
                max_steps=8,
                semantic=semantic,
                perturb_ids=prob > 0,
                perturb_prob=prob,
            )
            row = {
                "interface": interface,
                "perturb_prob": prob,
                "success_rate": summary["success_rate"],
                "avg_steps": summary["avg_steps"],
                "raw_invalid": sum(r["raw_invalid"] for r in summary["results"]),
                "repaired": sum(r["repaired"] for r in summary["results"]),
                "tasks": summary["tasks"],
            }
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    (OUT / "e1_perturb.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    asyncio.run(main())
