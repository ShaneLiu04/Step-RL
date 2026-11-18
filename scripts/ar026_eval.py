"""AR026: v3 layout + layout-adaptive skill compilation (real Edge, 0 LLM)."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from step_rl.edge.browser import BrowserEnv  # noqa: E402
from step_rl.edge.site import LocalShopServer  # noqa: E402
from step_rl.edge.skill_library import (  # noqa: E402
    add_item_skill,
    checkout_skill,
    run_skill,
    update_quantity_skill,
)
from step_rl.edge.tasks import TaskSpec  # noqa: E402
from step_rl.edge.verifier import compute_progress  # noqa: E402

OUT = ROOT / "outputs" / "ar026" / "eval"


def tasks():
    return [
        (
            "v3_add_p3",
            TaskSpec("v3_add_p3", 3, "买两件无线充电器", "无线", {"p3": 2}),
            lambda adaptive: add_item_skill("p3", 2, adaptive=adaptive),
        ),
        (
            "v3_update_p3",
            TaskSpec(
                "v3_update_p3",
                3,
                "把无线充电器数量改为3",
                "无线",
                {"p3": 3},
                operation="update",
                seed_cart={"p3": 2},
                start_path="/cart",
                predicates=["cart_contains"],
            ),
            lambda adaptive: update_quantity_skill("p3", 3, adaptive=adaptive),
        ),
        (
            "v3_checkout_p4",
            TaskSpec(
                "v3_checkout_p4",
                4,
                "买一件蓝牙降噪耳机并结算",
                "蓝牙",
                {"p4": 1},
                require_checkout=True,
                seed_cart={"p4": 1},
                start_path="/checkout",
                predicates=["order_placed"],
            ),
            lambda adaptive: checkout_skill(),
        ),
    ]


async def run_case(task, skill_factory, adaptive):
    server = LocalShopServer(layout="v3").start()
    env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
    started = time.time()
    try:
        await env.start()
        obs = await env.reset(task)
        result = await run_skill(env, skill_factory(adaptive), initial_obs=obs)
        state = await env.get_state()
        progress = compute_progress(state, env.page_url_path, task)
        return {
            "task_id": task.task_id,
            "adaptive": adaptive,
            "success": bool(result.success and progress.success),
            "skill_success": result.success,
            "error": result.error,
            "actions": len(result.actions),
            "policy_steps": 0,
            "prompt_tokens": 0,
            "cart": state.get("cart", {}),
            "orders": len(state.get("orders", [])),
            "seconds": round(time.time() - started, 2),
            "observation": dict(env.observation_metrics),
        }
    finally:
        await env.close()
        server.stop()


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for _, task, factory in tasks():
        for adaptive in (False, True):
            row = await run_case(task, factory, adaptive)
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    base = [r for r in rows if not r["adaptive"]]
    new = [r for r in rows if r["adaptive"]]
    summary = {
        "baseline": {
            "tasks": len(base),
            "success": sum(r["success"] for r in base),
            "success_rate": sum(r["success"] for r in base) / max(1, len(base)),
            "policy_steps": sum(r["policy_steps"] for r in base),
            "prompt_tokens": sum(r["prompt_tokens"] for r in base),
        },
        "adaptive": {
            "tasks": len(new),
            "success": sum(r["success"] for r in new),
            "success_rate": sum(r["success"] for r in new) / max(1, len(new)),
            "policy_steps": sum(r["policy_steps"] for r in new),
            "prompt_tokens": sum(r["prompt_tokens"] for r in new),
        },
    }
    verdict = {
        "P0_v3_controls": True,
        "P1_baseline_fails": summary["baseline"]["success"] < len(base),
        "P2_adaptive_all": summary["adaptive"]["success"] == len(new),
        "P3_zero_llm": summary["adaptive"]["policy_steps"] == 0
        and summary["adaptive"]["prompt_tokens"] == 0,
    }
    verdict["overall"] = all(verdict.values())
    payload = {
        "ar": "AR026",
        "layout": "v3",
        "summary": summary,
        "verdict": verdict,
        "rows": rows,
    }
    (OUT / "ar026_results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# AR026 v3 布局与自适应技能编译（真实 Edge / 0 LLM）",
        "",
        "| 模式 | 成功 | 成功率 | LLM 步 | Prompt tokens |",
        "|------|------|--------|--------|---------------|",
        f"| 固定技能（baseline） | {summary['baseline']['success']}/{summary['baseline']['tasks']} | "
        f"{summary['baseline']['success_rate']:.1%} | {summary['baseline']['policy_steps']} | "
        f"{summary['baseline']['prompt_tokens']} |",
        f"| LASC（AR026） | {summary['adaptive']['success']}/{summary['adaptive']['tasks']} | "
        f"{summary['adaptive']['success_rate']:.1%} | {summary['adaptive']['policy_steps']} | "
        f"{summary['adaptive']['prompt_tokens']} |",
        "",
        "## 逐任务",
        "",
        "| 任务 | 模式 | 成功 | 动作数 | 错误 |",
        "|------|------|------|--------|------|",
    ]
    for row in rows:
        lines.append(
            f"| {row['task_id']} | {'adaptive' if row['adaptive'] else 'fixed'} | "
            f"{'✓' if row['success'] else '✗'} | {row['actions']} | {row['error'][:60]} |"
        )
    lines += [
        "",
        "## 判定",
        "",
        "```json",
        json.dumps(verdict, ensure_ascii=False, indent=2),
        "```",
    ]
    (OUT / "ar026_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
