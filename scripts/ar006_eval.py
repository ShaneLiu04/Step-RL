"""AR006: constraint-aware task planning on real instructions."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from step_rl.edge.browser import BrowserEnv  # noqa: E402
from step_rl.edge.hierarchical import run_hierarchy  # noqa: E402
from step_rl.edge.modeling import (  # noqa: E402
    load_multi_adapter,
    resolve_model_path,
    set_seed,
)
from step_rl.edge.planner import (  # noqa: E402
    fetch_catalog,
    naive_plan,
    plan_instruction,
)
from step_rl.edge.site import LocalShopServer  # noqa: E402
from step_rl.edge.tasks import TaskSpec  # noqa: E402
from step_rl.edge.verifier import compute_progress  # noqa: E402

ADAPTERS = {
    "base": "outputs/ar004/sft_semantic",
    "quantity": "outputs/ar004/grpo_semantic_vgdp",
    "checkout": "outputs/ar004/grpo_semantic_sparse",
}
OUT = ROOT / "outputs" / "ar006" / "eval"

# instruction, expected targets, stock overrides
CASES = [
    ("买最便宜的商品并完成结算", {"p2": 1}, {}),
    ("买价格不超过300元的最贵商品并结算", {"p3": 1}, {}),
    ("买两件USB-C数据线并结算", {"p2": 2}, {}),
    ("买一件iPhone 15和两件数据线，完成结算", {"p1": 1, "p2": 2}, {}),
    ("预算650元，买无线充电器和蓝牙耳机各一件，并结算", {"p3": 1, "p4": 1}, {}),
    ("买三件蓝牙耳机并结算", {"p4": 3}, {}),
    ("买最贵的商品并结算", {"p1": 1}, {}),
    ("如果无线充电器缺货，就买蓝牙耳机，并结算", {"p4": 1}, {"p3": 0}),
]


async def run_condition(
    label: str,
    planner,
    layout: str = "v1",
    perturb: bool = False,
) -> dict:
    set_seed(42)
    model, tokenizer = load_multi_adapter(resolve_model_path(), ADAPTERS)
    results = []
    started = time.time()
    for instruction, expected, stock in CASES:
        server = LocalShopServer(
            layout=layout, stock_overrides=stock if stock else None
        ).start()
        env = BrowserEnv(
            server,
            channel="msedge",
            headless=True,
            semantic=True,
            perturb_ids=perturb,
        )
        try:
            catalog = fetch_catalog(server.base_url)
            spec = planner(instruction, catalog)
            planned = None if spec is None else dict(spec.targets)
            if spec is None:
                results.append(
                    {
                        "instruction": instruction,
                        "expected": expected,
                        "planned": None,
                        "plan_correct": False,
                        "success": False,
                        "steps": 0,
                    }
                )
                continue
            plan_correct = planned == expected
            first = next((c for c in catalog if c.pid in expected), catalog[0])
            expected_spec = TaskSpec(
                task_id="expected",
                level=5 if len(expected) > 1 else 4,
                goal=instruction,
                search_query=first.keywords[0] if first.keywords else first.name,
                targets=dict(expected),
                require_checkout=True,
            )
            await env.start()
            rollout = await run_hierarchy(
                env,
                spec,
                model,
                tokenizer,
                repair=False,
                max_steps_per_subtask=12,
                semantic=True,
            )
            state = await env.get_state()
            expected_ok = compute_progress(
                state, env.page_url_path, expected_spec
            ).success
            results.append(
                {
                    "instruction": instruction,
                    "expected": expected,
                    "planned": planned,
                    "plan_correct": plan_correct,
                    "success": expected_ok,
                    "own_success": rollout.success,
                    "steps": rollout.total_steps,
                }
            )
            print(
                f"[{label}] {instruction[:18]}... planned={planned} "
                f"correct={plan_correct} expected_success={expected_ok}",
                flush=True,
            )
        finally:
            await env.close()
            server.stop()
    count = max(1, len(results))
    return {
        "label": label,
        "layout": layout,
        "perturb_ids": perturb,
        "tasks": len(results),
        "plan_accuracy": sum(r["plan_correct"] for r in results) / count,
        "success_rate": sum(r["success"] for r in results) / count,
        "avg_steps": sum(r["steps"] for r in results) / count,
        "seconds": round(time.time() - started, 2),
        "results": results,
    }


async def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    OUT.mkdir(parents=True, exist_ok=True)
    reports = []
    for label, planner, layout, perturb in (
        ("naive_baseline_v1", naive_plan, "v1", False),
        ("constraint_planner_v1", plan_instruction, "v1", False),
        ("constraint_planner_v2_churn", plan_instruction, "v2", True),
    ):
        report = await run_condition(label, planner, layout, perturb)
        reports.append(report)
        (OUT / f"{label}.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {k: v for k, v in report.items() if k != "results"},
                ensure_ascii=False,
                indent=2,
            ),
            flush=True,
        )

    lines = [
        "# AR006 约束任务规划真实评测",
        "",
        "| 条件 | 布局 | ID churn | 规划准确率 | 任务成功率 | 平均步数 |",
        "|------|------|----------|------------|------------|----------|",
    ]
    for report in reports:
        lines.append(
            f"| {report['label']} | {report['layout']} | "
            f"{'是' if report['perturb_ids'] else '否'} | "
            f"{report['plan_accuracy']:.1%} | {report['success_rate']:.1%} | "
            f"{report['avg_steps']:.2f} |"
        )
    lines += [
        "",
        "## 逐指令",
        "",
        "| 指令 | 期望 | 规划 | 规划正确 | 执行成功 |",
        "|------|------|------|----------|----------|",
    ]
    for report in reports:
        for item in report["results"]:
            lines.append(
                f"| {item['instruction']} | {item['expected']} | "
                f"{item['planned']} | {'✓' if item['plan_correct'] else '✗'} | "
                f"{'✓' if item['success'] else '✗'} |"
            )
    lines.append("")
    (OUT / "ar006_report.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
