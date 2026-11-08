"""AR014 exact quantity and checkpoint recovery tests."""

from __future__ import annotations

import asyncio

import pytest

from step_rl.edge.browser import BrowserEnv
from step_rl.edge.site import LocalShopServer
from step_rl.edge.skill_library import add_item_skill, checkout_skill, run_skill
from step_rl.edge.tasks import TaskSpec
from step_rl.edge.verifier import compute_progress


def test_exact_quantity_verifier():
    task = TaskSpec(
        task_id="x",
        level=4,
        goal="x",
        search_query="x",
        targets={"p4": 2},
        require_checkout=True,
        exact_quantity=True,
    )
    state = {
        "query": "x",
        "cart": {"p4": 3},
        "form": {"name": "A", "address": "B"},
        "order": None,
        "visited": ["/search?q=x", "/product/p4", "/cart", "/checkout"],
    }
    assert not compute_progress(state, "/", task).success
    state["cart"] = {"p4": 2}
    state["order"] = {"id": "1", "items": {"p4": 2}}
    state["cart"] = {}
    assert compute_progress(state, "/order/1", task).success


def test_checkpoint_resumes_session():
    pytest.importorskip("playwright")

    task = TaskSpec(
        task_id="cp",
        level=4,
        goal="买两件蓝牙耳机并结算",
        search_query="蓝牙",
        targets={"p4": 2},
        require_checkout=True,
        exact_quantity=True,
    )

    async def runner():
        server = LocalShopServer().start()
        env1 = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
        try:
            try:
                await env1.start()
            except Exception as exc:  # pragma: no cover
                pytest.skip(f"browser unavailable: {exc}")
            await env1.reset(task)
            assert (await run_skill(env1, add_item_skill("p4", 2))).success
            state = await env1.save_state()
            await env1.close()

            env2 = BrowserEnv(
                server,
                channel="msedge",
                headless=True,
                semantic=True,
                storage_state=state,
            )
            try:
                await env2.start()
                assert (await run_skill(env2, checkout_skill())).success
                final = await env2.get_state()
                assert (final.get("order") or {}).get("items") == {"p4": 2}
                assert compute_progress(final, env2.page_url_path, task).success
            finally:
                await env2.close()
        finally:
            server.stop()

    asyncio.run(runner())
