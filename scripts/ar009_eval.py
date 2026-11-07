"""AR009: error observability and error-driven repair under form validation."""

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
from step_rl.edge.planner import fetch_catalog, plan_instruction  # noqa: E402
from step_rl.edge.site import LocalShopServer  # noqa: E402
from step_rl.edge.tasks import TaskSpec  # noqa: E402
from step_rl.edge.verifier import compute_progress  # noqa: E402

ADAPTERS = {
    "base": "outputs/ar004/sft_semantic",
    "quantity": "outputs/ar004/grpo_semantic_vgdp",
    "checkout": "outputs/ar004/grpo_semantic_sparse",
}
OUT = ROOT / "outputs" / "ar009" / "eval"
TASKS = [
    ("买一件无线充电器并结算", {"p3": 1}),
    ("买两件USB-C数据线并结算", {"p2": 2}),
]


async def run_case(model, tokenizer, instruction, expected, feedback, repair):
    server = LocalShopServer(
        checkout_name_requires_title=True,
        checkout_address_requires_road=True,
    ).start()
    env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
    started = time.time()
    try:
        catalog = fetch_catalog(server.base_url)
        spec = plan_instruction(instruction, catalog)
        first = next(c for c in catalog if c.pid in expected)
        expected_spec = TaskSpec(
            task_id="expected",
            level=5 if len(expected) > 1 else 4,
            goal=instruction,
            search_query=first.keywords[0],
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
            error_feedback=feedback,
            error_repair=repair,
        )
        state = await env.get_state()
        success = compute_progress(state, env.page_url_path, expected_spec).success
        return {
            "instruction": instruction,
            "expected": expected,
            "feedback": feedback,
            "repair": repair,
            "success": success,
            "steps": rollout.total_steps,
            "seconds": round(time.time() - started, 2),
        }
    finally:
        await env.close()
        server.stop()


async def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    set_seed(42)
    OUT.mkdir(parents=True, exist_ok=True)
    model, tokenizer = load_multi_adapter(resolve_model_path(), ADAPTERS)
    rows = []
    for label, feedback, repair in (
        ("baseline", False, False),
        ("observable", True, False),
        ("observable_repair", True, True),
    ):
        for instruction, expected in TASKS:
            row = await run_case(
                model, tokenizer, instruction, expected, feedback, repair
            )
            row["label"] = label
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    (OUT / "ar009_results.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# AR009 错误可观测与修复真实评测",
        "",
        "| 条件 | 任务 | 成功 | 步数 |",
        "|------|------|------|------|",
    ]
    for row in rows:
        lines.append(
            f"| {row['label']} | {row['instruction']} | "
            f"{'✓' if row['success'] else '✗'} | {row['steps']} |"
        )
    lines.append("")
    (OUT / "ar009_report.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
