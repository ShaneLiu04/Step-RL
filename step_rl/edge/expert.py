"""Scripted expert that solves tasks through the real browser.

The expert is a deterministic controller over the real observation.  Its
trajectories are used for behaviour cloning (SFT); they are not mock
demonstrations because every action is executed against the live shop.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from .browser import BrowserEnv
from .policy import build_prompt, render_action
from .site import PRODUCTS
from .tasks import SFT_TASKS, TaskSpec
from .verifier import compute_progress

NAME = "刘星言"
ADDRESS = "深圳市龙岗区坂田街道"


def _has(obs: Dict[str, Any], selector: str) -> bool:
    return any(e.get("selector") == selector for e in obs.get("elements", []))


def _value(obs: Dict[str, Any], selector: str) -> str:
    for element in obs.get("elements", []):
        if element.get("selector") == selector:
            return str(element.get("value", ""))
    return ""


def _satisfied_targets(state: Dict[str, Any], task: TaskSpec) -> List[str]:
    cart = state.get("cart") or {}
    return [pid for pid, qty in task.targets.items() if int(cart.get(pid, 0)) >= qty]


def expert_action(task: TaskSpec, obs: Dict[str, Any]) -> Dict[str, Any]:
    state = obs.get("state") or {}
    path = urlparse(obs.get("url", "/")).path
    cart = state.get("cart") or {}
    visited = state.get("visited") or []

    def act(action: str, params: Dict[str, Any], thought: str) -> Dict[str, Any]:
        return {"thought": thought, "action": action, "params": params}

    # Level 1: search only.
    if task.level == 1:
        if state.get("query") == task.search_query:
            return act("finish", {}, "搜索结果已出现，任务完成")
        if _has(obs, "#q") and _has(obs, "#search-btn"):
            if _value(obs, "#q") != task.search_query:
                return act(
                    "type", {"selector": "#q", "text": task.search_query}, "输入搜索词"
                )
            return act("click", {"selector": "#search-btn"}, "执行搜索")
        return act("goto", {"url": "/"}, "回到首页")

    order = state.get("order") or {}
    order_items = order.get("items") or {}
    if order_items and all(
        int(order_items.get(pid, 0)) >= qty for pid, qty in task.targets.items()
    ):
        return act("finish", {}, "订单已生成，任务完成")

    done = _satisfied_targets(state, task)
    pending = [pid for pid in task.targets if pid not in done]
    if pending:
        pid = pending[0]
        product_path = f"/product/{pid}"
        if path == product_path:
            remaining = task.targets[pid] - int(cart.get(pid, 0))
            remaining = max(1, remaining)
            if _has(obs, "#qty") and _value(obs, "#qty") != str(remaining):
                return act(
                    "type",
                    {"selector": "#qty", "text": str(remaining)},
                    f"设置数量 {remaining}",
                )
            if _has(obs, "#add-to-cart"):
                return act("click", {"selector": "#add-to-cart"}, "加入购物车")
            return act("goto", {"url": f"/add/{pid}?qty={remaining}"}, "加入购物车")
        if path.startswith("/product/"):
            # Wrong product page, search again.
            return act("goto", {"url": "/"}, "回到首页重新搜索")
        if not any(pid in u for u in visited):
            query = PRODUCTS[pid].keywords[0] if pid in PRODUCTS else task.search_query
            # Search flow: if results are visible, open the product directly.
            if state.get("query") == query and _has(obs, f"#product-{pid}"):
                return act("click", {"selector": f"#product-{pid}"}, "打开商品详情")
            if _has(obs, "#q") and _has(obs, "#search-btn"):
                if _value(obs, "#q") != query:
                    return act(
                        "type",
                        {"selector": "#q", "text": query},
                        "输入搜索词",
                    )
                return act("click", {"selector": "#search-btn"}, "执行搜索")
            return act("goto", {"url": f"/search?q={query}"}, "打开搜索结果")
        return act("goto", {"url": product_path}, "打开商品详情")

    if not task.require_checkout:
        return act("finish", {}, "购物车已包含目标商品，任务完成")

    if path != "/cart" and "/cart" not in {urlparse(u).path for u in visited}:
        if _has(obs, "#nav-cart"):
            return act("click", {"selector": "#nav-cart"}, "打开购物车")
        return act("goto", {"url": "/cart"}, "打开购物车")
    if path == "/cart" or not visited:
        if _has(obs, "#checkout-btn"):
            return act("click", {"selector": "#checkout-btn"}, "进入结算")
        return act("goto", {"url": "/checkout"}, "进入结算")
    if path == "/checkout":
        if not _value(obs, "#name").strip() and _has(obs, "#name"):
            return act("type", {"selector": "#name", "text": NAME}, "填写收货人")
        if not _value(obs, "#address").strip() and _has(obs, "#address"):
            return act("type", {"selector": "#address", "text": ADDRESS}, "填写地址")
        return act("click", {"selector": "#place-order"}, "提交订单")
    if state.get("order"):
        return act("finish", {}, "订单已生成，任务完成")
    return act("goto", {"url": "/cart"}, "返回购物车")


async def collect_expert_trajectories(
    server_url: str,
    out_path: str,
    tasks: Optional[List[TaskSpec]] = None,
    repeats: int = 2,
    max_steps: int = 12,
    headless: bool = True,
    channel: str = "msedge",
) -> Dict[str, Any]:
    from .site import LocalShopServer

    # Caller normally owns the server; this helper can also be used standalone.
    own_server = server_url is None
    server = LocalShopServer().start() if own_server else None
    env = BrowserEnv(
        server if server else _ProxyServer(server_url),  # type: ignore[arg-type]
        channel=channel,
        headless=headless,
    )
    records: List[Dict[str, Any]] = []
    stats = {"episodes": 0, "success": 0, "steps": 0}
    tasks = tasks or SFT_TASKS
    try:
        await env.start()
        for task in tasks:
            for repeat in range(repeats):
                obs = await env.reset(task)
                history: List[str] = []
                steps: List[Dict[str, Any]] = []
                progress = compute_progress(obs["state"], obs["url"], task)
                prev_phi = progress.progress
                success = False
                for _ in range(max_steps):
                    missing_before = list(progress.missing)
                    page_before = obs["url"]
                    prompt = build_prompt(
                        task.goal,
                        obs,
                        history,
                        progress=prev_phi,
                        missing=missing_before,
                    )
                    action = expert_action(task, obs)
                    response = render_action(action)
                    exec_result = await env.execute(action)
                    obs = await env.observe()
                    progress = compute_progress(obs["state"], obs["url"], task)
                    phi = progress.progress
                    steps.append(
                        {
                            "prompt": prompt,
                            "response": response,
                            "action": action,
                            "exec_ok": exec_result["ok"],
                            "error": exec_result.get("error", ""),
                            "phi_before": prev_phi,
                            "phi_after": phi,
                            "success": phi >= 1.0,
                            "page": page_before,
                            "missing": missing_before,
                        }
                    )
                    history.append(
                        f"{response} -> {'ok' if exec_result['ok'] else 'fail'} "
                        f"phi={phi:.2f}"
                    )
                    prev_phi = phi
                    success = phi >= 1.0
                    if exec_result.get("terminal") or success:
                        break
                records.append(
                    {
                        "task_id": task.task_id,
                        "level": task.level,
                        "goal": task.goal,
                        "success": success,
                        "final_progress": prev_phi,
                        "repeat": repeat,
                        "steps": steps,
                    }
                )
                stats["episodes"] += 1
                stats["success"] += int(success)
                stats["steps"] += len(steps)
    finally:
        await env.close()
        if server:
            server.stop()

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    stats["success_rate"] = stats["success"] / max(1, stats["episodes"])
    stats["out_path"] = str(out)
    return stats


class _ProxyServer:
    """Minimal adapter so BrowserEnv can point at an already running server."""

    def __init__(self, base_url: str) -> None:
        parsed = urlparse(base_url)
        self.host = parsed.hostname or "127.0.0.1"
        self.base_url = base_url.rstrip("/")


def main() -> None:
    import argparse

    from .site import LocalShopServer

    parser = argparse.ArgumentParser(description="Collect real expert trajectories")
    parser.add_argument("--out", default="outputs/ar001/expert_sft.jsonl")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--headless", action="store_true", default=True)
    args = parser.parse_args()
    server = LocalShopServer().start()
    try:
        stats = asyncio.run(
            collect_expert_trajectories(server.base_url, args.out, repeats=args.repeats)
        )
    finally:
        server.stop()
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
