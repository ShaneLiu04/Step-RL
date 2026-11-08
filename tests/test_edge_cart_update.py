"""AR015 cart update endpoint, exact predicate and skill tests."""

from __future__ import annotations

import asyncio
import http.cookiejar
import json
import urllib.request

import pytest

from step_rl.edge.browser import BrowserEnv
from step_rl.edge.site import LocalShopServer
from step_rl.edge.skill_library import run_skill_hierarchy
from step_rl.edge.tasks import TaskSpec
from step_rl.edge.verifier import compute_progress


def _opener(server):
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )


def test_cart_seed_and_update_routes():
    server = LocalShopServer().start()
    try:
        opener = _opener(server)
        opener.open(server.base_url + "/api/cart/set?pid=p4&qty=2").read()
        opener.open(server.base_url + "/update/p4?qty=4").read()
        state = json.loads(
            opener.open(server.base_url + "/api/state").read().decode("utf-8")
        )
        assert state["cart"] == {"p4": 4}
    finally:
        server.stop()


def test_exact_cart_predicate():
    task = TaskSpec(
        task_id="up",
        level=2,
        goal="x",
        search_query="x",
        targets={"p3": 3},
        operation="update",
        predicates=["cart_quantity_exact"],
        exact_quantity=True,
    )
    assert compute_progress({"cart": {"p3": 3}}, "/cart", task).success
    assert not compute_progress({"cart": {"p3": 2}}, "/cart", task).success


def test_update_skill_real_browser():
    pytest.importorskip("playwright")

    task = TaskSpec(
        task_id="up",
        level=2,
        goal="把购物车中的无线充电器数量改为3",
        search_query="无线",
        targets={"p3": 3},
        seed_cart={"p3": 1},
        operation="update",
        predicates=["cart_quantity_exact"],
        exact_quantity=True,
    )

    async def runner():
        server = LocalShopServer().start()
        env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
        try:
            try:
                await env.start()
            except Exception as exc:  # pragma: no cover
                pytest.skip(f"browser unavailable: {exc}")
            rollout = await run_skill_hierarchy(env, task, None, None, fallback=False)
            assert rollout.success
            state = await env.get_state()
            assert state["cart"] == {"p3": 3}
        finally:
            await env.close()
            server.stop()

    asyncio.run(runner())
