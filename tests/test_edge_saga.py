"""AR017 order cancellation and Saga compensation tests."""

from __future__ import annotations

import asyncio
import http.cookiejar
import json
import urllib.parse
import urllib.request

import pytest

from step_rl.edge.browser import BrowserEnv
from step_rl.edge.runtime import run_order_sequence
from step_rl.edge.site import LocalShopServer
from step_rl.edge.tasks import TaskSpec
from step_rl.edge.verifier import compute_progress


def _opener(server):
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )


def test_cancel_route_sets_status():
    server = LocalShopServer().start()
    try:
        opener = _opener(server)
        opener.open(server.base_url + "/add/p3?qty=1").read()
        opener.open(server.base_url + "/checkout").read()
        body = urllib.parse.urlencode({"name": "A先生", "address": "深圳路1号"}).encode(
            "utf-8"
        )
        request = urllib.request.Request(
            server.base_url + "/place-order", data=body, method="POST"
        )
        opener.open(request).read()
        state = json.loads(
            opener.open(server.base_url + "/api/state").read().decode("utf-8")
        )
        order_id = state["orders"][0]["id"]
        opener.open(server.base_url + f"/cancel/{order_id}").read()
        state = json.loads(
            opener.open(server.base_url + "/api/state").read().decode("utf-8")
        )
        assert state["orders"][0]["status"] == "cancelled"
    finally:
        server.stop()


def test_cancelled_verifier():
    task = TaskSpec(
        task_id="s",
        level=5,
        goal="x",
        search_query="x",
        targets={"p3": 1},
        order_sequence=[{"p3": 1}],
        compensate_on_failure=True,
    )
    assert compute_progress(
        {"orders": [{"id": "1", "items": {"p3": 1}, "status": "cancelled"}]},
        "/",
        task,
    ).success
    assert not compute_progress(
        {"orders": [{"id": "1", "items": {"p3": 1}, "status": "active"}]},
        "/",
        task,
    ).success


def test_saga_cancels_completed_order():
    pytest.importorskip("playwright")

    task = TaskSpec(
        task_id="saga",
        level=5,
        goal="第一单成功，第二单缺货则取消第一单",
        search_query="无线",
        targets={"p3": 1, "p4": 2},
        require_checkout=True,
        order_sequence=[{"p3": 1}, {"p4": 2}],
        compensate_on_failure=True,
    )

    async def runner():
        server = LocalShopServer(stock_overrides={"p4": 0}).start()
        env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
        try:
            try:
                await env.start()
            except Exception as exc:  # pragma: no cover
                pytest.skip(f"browser unavailable: {exc}")
            result = await run_order_sequence(env, task, None, None, compensate=True)
            assert result["success"]
            assert all(order["status"] == "cancelled" for order in result["orders"])
        finally:
            await env.close()
            server.stop()

    asyncio.run(runner())
