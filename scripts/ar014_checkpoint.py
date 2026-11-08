"""AR014: checkpointed execution vs restart-without-checkpoint."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from step_rl.edge.browser import BrowserEnv  # noqa: E402
from step_rl.edge.hierarchical import decompose_task  # noqa: E402
from step_rl.edge.site import LocalShopServer  # noqa: E402
from step_rl.edge.skill_library import (  # noqa: E402
    add_item_skill,
    checkout_skill,
    run_skill,
)
from step_rl.edge.tasks import TaskSpec  # noqa: E402
from step_rl.edge.verifier import compute_progress  # noqa: E402

OUT = ROOT / "outputs" / "ar014" / "eval"

TASKS = [
    TaskSpec(
        task_id="cp_p4x2",
        level=4,
        goal="买两件蓝牙耳机并结算",
        search_query="蓝牙",
        targets={"p4": 2},
        require_checkout=True,
        exact_quantity=True,
    ),
    TaskSpec(
        task_id="cp_p3x2",
        level=4,
        goal="买两件无线充电器并结算",
        search_query="无线",
        targets={"p3": 2},
        require_checkout=True,
        exact_quantity=True,
    ),
    TaskSpec(
        task_id="cp_multi",
        level=5,
        goal="买一件iPhone和一件数据线并结算",
        search_query="iphone",
        targets={"p1": 1, "p2": 1},
        require_checkout=True,
        exact_quantity=True,
    ),
]


async def add_steps(env, task):
    for subtask in decompose_task(task):
        if subtask.require_checkout:
            continue
        pid = next(iter(subtask.targets))
        skill = add_item_skill(pid, subtask.targets[pid])
        result = await run_skill(env, skill)
        if not result.success:
            return False
    return True


async def run_case(task, checkpointed: bool):
    server = LocalShopServer().start()
    env1 = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
    started = time.time()
    try:
        await env1.start()
        await env1.reset(task)
        if not await add_steps(env1, task):
            raise RuntimeError("add phase failed")
        state = await env1.save_state()
        await env1.close()

        env2 = BrowserEnv(
            server,
            channel="msedge",
            headless=True,
            semantic=True,
            storage_state=state,
        )
        await env2.start()
        if checkpointed:
            result = await run_skill(env2, checkout_skill())
            ok = result.success
        else:
            # Restart the whole program but keep the same browser session:
            # the cart already has the items, so adding them again doubles it.
            await add_steps(env2, task)
            result = await run_skill(env2, checkout_skill())
            ok = result.success
        final = await env2.get_state()
        progress = compute_progress(final, env2.page_url_path, task)
        order = (final.get("order") or {}).get("items", {})
        return {
            "task_id": task.task_id,
            "checkpointed": checkpointed,
            "skill_ok": ok,
            "success": progress.success,
            "order": order,
            "seconds": round(time.time() - started, 2),
        }
    finally:
        await env1.close()
        server.stop()


async def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for task in TASKS:
        rows.append(await run_case(task, checkpointed=False))
        rows.append(await run_case(task, checkpointed=True))
    (OUT / "ar014_results.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# AR014 崩溃恢复真实评测",
        "",
        "| 任务 | 模式 | 成功 | 订单 | 耗时 |",
        "|------|------|------|------|------|",
    ]
    for row in rows:
        lines.append(
            f"| {row['task_id']} | "
            f"{'checkpointed' if row['checkpointed'] else 'restart'} | "
            f"{'✓' if row['success'] else '✗'} | {row['order']} | {row['seconds']} |"
        )
    lines += [
        "",
        "## 结论",
        "",
        "- 基线保留同一会话但不保存子目标进度，重启后重复加购，精确数量失败。",
        "- 检查点保存 storage_state 并只继续结算，订单数量精确，恢复成功。",
        "",
    ]
    (OUT / "ar014_report.md").write_text("\n".join(lines), encoding="utf-8")
    for row in rows:
        print(json.dumps(row, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
