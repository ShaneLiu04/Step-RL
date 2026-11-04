"""Second storefront layout (ShopLite) tests."""

from __future__ import annotations

import asyncio
import http.cookiejar
import json
import urllib.parse
import urllib.request

import pytest

from step_rl.edge.site import LocalShopServer
from step_rl.edge.tasks import TASK_BY_ID


@pytest.fixture()
def v2_client():
    server = LocalShopServer(layout="v2").start()
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def get(path):
        return opener.open(server.base_url + path).read().decode("utf-8")

    def post(path, data):
        body = urllib.parse.urlencode(data).encode("utf-8")
        request = urllib.request.Request(
            server.base_url + path, data=body, method="POST"
        )
        return opener.open(request).read().decode("utf-8")

    def state():
        return json.loads(get("/api/state"))

    yield get, post, state
    server.stop()


def test_v2_home_has_semantic_names_and_no_v1_ids(v2_client):
    get, post, state = v2_client
    html = get("/")
    assert "ShopLite" in html
    assert "aria-label='搜索商品'" in html
    assert "aria-label='搜索'" in html
    assert "id='q'" not in html
    assert "id='search-btn'" not in html


def test_v2_checkout_flow(v2_client):
    get, post, state = v2_client
    get("/search?q=usb")
    get("/product/p2")
    get("/add/p2?qty=2")
    get("/cart")
    get("/checkout")
    post("/place-order", {"name": "Agent", "address": "Shenzhen"})
    st = state()
    assert st["order"] is not None
    assert st["order"]["items"]["p2"] == 2


async def _v2_semantic_browser_execution():
    pytest.importorskip("playwright")
    from step_rl.edge.browser import BrowserEnv

    server = LocalShopServer(layout="v2").start()
    env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
    try:
        try:
            await env.start()
        except Exception as exc:  # pragma: no cover
            pytest.skip(f"browser unavailable: {exc}")
        obs = await env.reset(TASK_BY_ID["sft_search_p1"])
        search_input = next(
            e
            for e in obs["elements"]
            if e["role"] == "textbox" and "搜索" in e["accessible_name"]
        )
        assert (
            await env.execute(
                {
                    "action": "type",
                    "params": {"element": search_input["eid"], "text": "iphone"},
                }
            )
        )["ok"]
        obs = await env.observe()
        search_button = next(
            e
            for e in obs["elements"]
            if e["role"] == "button" and e["accessible_name"] == "搜索"
        )
        assert (
            await env.execute(
                {"action": "click", "params": {"element": search_button["eid"]}}
            )
        )["ok"]
        state = await env.get_state()
        assert state["query"] == "iphone"
    finally:
        await env.close()
        server.stop()


def test_v2_semantic_browser_execution():
    asyncio.run(_v2_semantic_browser_execution())
