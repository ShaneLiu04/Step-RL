"""AR013: adversarial UI grounding — LLM baseline vs skill runtime."""

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
from step_rl.edge.runtime import run_task  # noqa: E402
from step_rl.edge.site import LocalShopServer  # noqa: E402
from step_rl.edge.tasks import TaskSpec  # noqa: E402
from step_rl.edge.verifier import compute_progress  # noqa: E402

ADAPTERS = {
    "base": "outputs/ar004/sft_semantic",
    "quantity": "outputs/ar004/grpo_semantic_vgdp",
    "checkout": "outputs/ar004/grpo_semantic_sparse",
}
TASKS = [
    ("买1件无线充电器并结算", {"p3": 1}),
    ("买2件蓝牙耳机并结算", {"p4": 2}),
    ("买1件iPhone 15和1件USB-C数据线，并结算", {"p1": 1, "p2": 1}),
]
OUT = ROOT / "outputs" / "ar013" / "eval"


def expected_spec(instruction, expected, catalog):
    first = next(c for c in catalog if c.pid in expected)
    return TaskSpec(
        task_id="expected",
        level=5 if len(expected) > 1 else 4,
        goal=instruction,
        search_query=first.keywords[0],
        targets=dict(expected),
        require_checkout=True,
    )


async def run_case(model, tokenizer, label, instruction, expected):
    server = LocalShopServer(injection=True).start()
    env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
    started = time.time()
    try:
        catalog = fetch_catalog(server.base_url)
        spec = expected_spec(instruction, expected, catalog)
        await env.start()
        if label == "baseline_llm":
            planned = plan_instruction(instruction, catalog)
            rollout = await run_hierarchy(
                env,
                planned,
                model,
                tokenizer,
                repair=False,
                max_steps_per_subtask=12,
                semantic=True,
            )
        else:
            result = await run_task(env, instruction, model, tokenizer)
            rollout = result
        state = await env.get_state()
        success = compute_progress(state, env.page_url_path, spec).success
        order = (state.get("order") or {}).get("items", {})
        return {
            "label": label,
            "instruction": instruction,
            "expected": expected,
            "success": success,
            "order": order,
            "steps": (
                len(rollout["steps"])
                if isinstance(rollout, dict)
                else rollout.total_steps
            ),
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
    for label in ("baseline_llm", "runtime_skill"):
        for instruction, expected in TASKS:
            row = await run_case(model, tokenizer, label, instruction, expected)
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    (OUT / "ar013_results.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# AR013 对抗 UI 接地真实评测",
        "",
        "| 条件 | 任务 | 成功 | 订单 | 步数 |",
        "|------|------|------|------|------|",
    ]
    for row in rows:
        lines.append(
            f"| {row['label']} | {row['instruction']} | "
            f"{'✓' if row['success'] else '✗'} | {row['order']} | {row['steps']} |"
        )
    lines.append("")
    (OUT / "ar013_report.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
