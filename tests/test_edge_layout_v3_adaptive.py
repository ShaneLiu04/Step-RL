"""AR026: third storefront layout + layout-adaptive skill compilation."""

from __future__ import annotations

import asyncio
import http.cookiejar
import json
import urllib.parse
import urllib.request

import pytest

from step_rl.edge.site import LocalShopServer
from step_rl.edge.tasks import TaskSpec


@pytest.fixture()
def v3_client():
    server = LocalShopServer(layout="v3").start()
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


def _add_task():
    return TaskSpec(
        task_id="v3_add_p3",
        level=3,
        goal="买两件无线充电器",
        search_query="无线",
        targets={"p3": 2},
    )


def _update_task():
    return TaskSpec(
        task_id="v3_update_p3",
        level=3,
        goal="把无线充电器数量改为3",
        search_query="无线",
        targets={"p3": 3},
        operation="update",
        seed_cart={"p3": 2},
        start_path="/cart",
    )


def _checkout_task():
    return TaskSpec(
        task_id="v3_checkout_p4",
        level=4,
        goal="买一件蓝牙降噪耳机并结算",
        search_query="蓝牙",
        targets={"p4": 1},
        require_checkout=True,
        seed_cart={"p4": 1},
        start_path="/checkout",
    )


async def _env(task):
    pytest.importorskip("playwright")
    from step_rl.edge.browser import BrowserEnv

    server = LocalShopServer(layout="v3").start()
    env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
    try:
        await env.start()
    except Exception as exc:  # pragma: no cover
        server.stop()
        pytest.skip(f"browser unavailable: {exc}")
    obs = await env.reset(task)
    return server, env, obs


def test_v3_home_has_no_ids_and_new_controls(v3_client):
    get, post, state = v3_client
    html = get("/")
    assert "ShopEdge" in html
    assert "role='searchbox'" in html
    assert "aria-label='查找'" in html
    assert "id='q'" not in html
    assert "id='search-btn'" not in html
    product = get("/product/p3")
    assert "role='spinbutton'" in product
    assert "aria-label='增加数量'" in product
    assert "id='qty'" not in product


def test_v3_fixed_skill_fails_real():
    async def run():
        from step_rl.edge.skill_library import add_item_skill, run_skill

        task = _add_task()
        server, env, obs = await _env(task)
        try:
            result = await run_skill(
                env, add_item_skill("p3", 2, adaptive=False), initial_obs=obs
            )
            state = await env.get_state()
            assert not result.success
            assert state.get("cart", {}).get("p3", 0) == 0
        finally:
            await env.close()
            server.stop()

    asyncio.run(run())


def test_v3_adaptive_add_item_real():
    async def run():
        from step_rl.edge.skill_library import add_item_skill, run_skill

        task = _add_task()
        server, env, obs = await _env(task)
        try:
            result = await run_skill(
                env, add_item_skill("p3", 2, adaptive=True), initial_obs=obs
            )
            state = await env.get_state()
            assert result.success
            assert state["cart"]["p3"] == 2
        finally:
            await env.close()
            server.stop()

    asyncio.run(run())


def test_v3_adaptive_update_quantity_real():
    async def run():
        from step_rl.edge.skill_library import run_skill, update_quantity_skill

        task = _update_task()
        server, env, obs = await _env(task)
        try:
            result = await run_skill(
                env, update_quantity_skill("p3", 3, adaptive=True), initial_obs=obs
            )
            state = await env.get_state()
            assert result.success
            assert state["cart"]["p3"] == 3
        finally:
            await env.close()
            server.stop()

    asyncio.run(run())


def test_v3_adaptive_checkout_real():
    async def run():
        from step_rl.edge.skill_library import checkout_skill, run_skill

        task = _checkout_task()
        server, env, obs = await _env(task)
        try:
            result = await run_skill(env, checkout_skill(), initial_obs=obs)
            state = await env.get_state()
            assert result.success
            assert state["order"] is not None
            assert state["order"]["items"]["p4"] == 1
        finally:
            await env.close()
            server.stop()

    asyncio.run(run())
