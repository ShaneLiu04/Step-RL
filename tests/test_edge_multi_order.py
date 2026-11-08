"""AR016 order history, sequence verifier and ordered execution."""

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


def _client(server):
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )

    def get(path):
        return opener.open(server.base_url + path).read().decode("utf-8")

    def post(path, data):
        body = urllib.parse.urlencode(data).encode("utf-8")
        request = urllib.request.Request(
            server.base_url + path, data=body, method="POST"
        )
        return opener.open(request).read().decode("utf-8")

    return get, post


def test_order_history_keeps_multiple_orders():
    server = LocalShopServer().start()
    try:
        get, post = _client(server)
        for pid in ("p3", "p2"):
            get(f"/add/{pid}?qty=1")
            get("/checkout")
            post("/place-order", {"name": "A先生", "address": "深圳路1号"})
        state = json.loads(get("/api/state"))
        assert len(state["orders"]) == 2
        assert len({o["id"] for o in state["orders"]}) == 2
    finally:
        server.stop()


def test_sequence_verifier():
    task = TaskSpec(
        task_id="m",
        level=5,
        goal="x",
        search_query="x",
        targets={"p3": 1, "p2": 2},
        require_checkout=True,
        order_sequence=[{"p3": 1}, {"p2": 2}],
    )
    state = {
        "orders": [
            {"id": "1", "items": {"p3": 1}},
            {"id": "2", "items": {"p2": 2}},
        ]
    }
    assert compute_progress(state, "/order/2", task).success
    state["orders"] = [{"id": "1", "items": {"p3": 1, "p2": 2}}]
    assert not compute_progress(state, "/order/1", task).success


def test_ordered_runtime_real_browser():
    pytest.importorskip("playwright")

    task = TaskSpec(
        task_id="m",
        level=5,
        goal="先买无线充电器，再买两件数据线",
        search_query="无线",
        targets={"p3": 1, "p2": 2},
        require_checkout=True,
        order_sequence=[{"p3": 1}, {"p2": 2}],
    )

    async def runner():
        server = LocalShopServer().start()
        env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
        try:
            try:
                await env.start()
            except Exception as exc:  # pragma: no cover
                pytest.skip(f"browser unavailable: {exc}")
            result = await run_order_sequence(env, task, None, None)
            assert result["success"]
            assert [o["items"] for o in result["orders"]] == [
                {"p3": 1},
                {"p2": 2},
            ]
        finally:
            await env.close()
            server.stop()

    asyncio.run(runner())
