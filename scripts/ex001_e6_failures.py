"""E6: classify failures from real AR001-AR006 result JSONs."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs" / "ex001"

SOURCES = {
    "AR001 SFT": "outputs/ar001/eval/sft.json",
    "AR001 SFT+repair": "outputs/ar001/eval/sft_repair.json",
    "AR001 sparse": "outputs/ar001/eval/sparse_grpo_repair.json",
    "AR001 VGDP": "outputs/ar001/eval/vgdp_grpo_repair.json",
    "AR001 router": "outputs/ar001/eval/router.json",
    "AR003 hierarchy": "outputs/ar003/eval/hierarchical.json",
    "AR004 semantic": "outputs/ar004/eval/semantic_stable.json",
    "AR004 semantic churn": "outputs/ar004/eval/semantic_id_churn.json",
    "AR005 selector v2": "outputs/ar005/eval/selector_v2.json",
    "AR005 selector v2 churn": "outputs/ar005/eval/selector_v2_churn.json",
    "AR005 semantic v2": "outputs/ar005/eval/semantic_v2_zero_shot.json",
    "AR005 semantic v2 churn": "outputs/ar005/eval/semantic_v2_churn.json",
    "AR006 naive": "outputs/ar006/eval/naive_baseline_v1.json",
    "AR006 planner": "outputs/ar006/eval/constraint_planner_v1.json",
    "AR006 planner churn": "outputs/ar006/eval/constraint_planner_v2_churn.json",
}


def stage(progress: float) -> str:
    if progress <= 0.15:
        return "search/navigation"
    if progress < 0.60:
        return "product/cart"
    if progress < 0.85:
        return "checkout/form"
    return "order/final"


def main() -> None:
    rows = []
    for label, rel in SOURCES.items():
        path = ROOT / rel
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        results = data.get("results", [])
        failures = [r for r in results if not r.get("success")]
        stages = {
            "search/navigation": 0,
            "product/cart": 0,
            "checkout/form": 0,
            "order/final": 0,
            "planning/constraint": 0,
        }
        for item in failures:
            if "final_progress" in item:
                stages[stage(float(item["final_progress"]))] += 1
            else:
                stages["planning/constraint"] += 1
        rows.append(
            {
                "condition": label,
                "tasks": len(results),
                "success_rate": data.get("success_rate"),
                "failures": len(failures),
                "failure_stages": stages,
                "failed_tasks": [
                    r.get("task_id", r.get("instruction")) for r in failures
                ],
            }
        )
    (OUT / "e6_failures.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
