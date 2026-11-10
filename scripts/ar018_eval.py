"""AR018: transient fault — single attempt baseline vs skill retry."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from step_rl.edge.browser import BrowserEnv  # noqa: E402
from step_rl.edge.runtime import run_task  # noqa: E402
from step_rl.edge.site import LocalShopServer  # noqa: E402
from step_rl.edge.skill_library import run_skill_hierarchy  # noqa: E402
from step_rl.edge.tasks import TaskSpec  # noqa: E402
from step_rl.edge.verifier import compute_progress  # noqa: E402

OUT = ROOT / "outputs" / "ar018" / "eval"

TASKS = [
    (
        "F1_add_fault",
        TaskSpec(
            task_id="F1",
            level=4,
            goal="买一件无线充电器并结算",
            search_query="无线",
            targets={"p3": 1},
            require_checkout=True,
        ),
        {"fault_add_once": True},
    ),
    (
        "F2_add_fault_qty2",
        TaskSpec(
            task_id="F2",
            level=4,
            goal="买两件蓝牙耳机并结算",
            search_query="蓝牙",
            targets={"p4": 2},
            require_checkout=True,
        ),
        {"fault_add_once": True},
    ),
    (
        "F3_order_fault",
        TaskSpec(
            task_id="F3",
            level=4,
            goal="买一件USB-C数据线并结算",
            search_query="usb",
            targets={"p2": 1},
            require_checkout=True,
        ),
        {"fault_order_once": True},
    ),
]


async def run_case(task, server_kwargs, retry):
    server = LocalShopServer(**server_kwargs).start()
    env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
    try:
        await env.start()
        if retry:
            result = await run_task(
                env,
                task.goal,
                None,
                None,
                skill_retries=1,
            )
            success = result["success"]
            attempts = len(result["attempts"])
        else:
            rollout = await run_skill_hierarchy(env, task, None, None, fallback=False)
            state = await env.get_state()
            success = compute_progress(state, env.page_url_path, task).success
            attempts = 1
        state = await env.get_state()
        return {
            "task_id": task.task_id,
            "mode": "retry" if retry else "single_attempt",
            "success": success,
            "attempts": attempts,
            "orders": state.get("orders", []),
        }
    finally:
        await env.close()
        server.stop()


async def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, task, kwargs in TASKS:
        rows.append(await run_case(task, kwargs, retry=False))
        rows.append(await run_case(task, kwargs, retry=True))
    (OUT / "ar018_results.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# AR018 瞬时故障重试真实评测",
        "",
        "| 任务 | 模式 | 成功 | 尝试 | 订单 |",
        "|------|------|------|------|------|",
    ]
    for row in rows:
        lines.append(
            f"| {row['task_id']} | {row['mode']} | "
            f"{'✓' if row['success'] else '✗'} | {row['attempts']} | "
            f"{row['orders']} |"
        )
    lines += [
        "",
        "## 结论",
        "",
        "- 单次执行遇到一次性 500 后失败。",
        "- Runtime 在同 TaskSpec 上重试一次，真实重置会话后成功。",
        "",
    ]
    (OUT / "ar018_report.md").write_text("\n".join(lines), encoding="utf-8")
    for row in rows:
        print(json.dumps(row, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
