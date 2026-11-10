"""AR018 transient fault injection and retry tests."""

from __future__ import annotations

import asyncio
import http.cookiejar
import urllib.error
import urllib.parse
import urllib.request

import pytest

from step_rl.edge.browser import BrowserEnv
from step_rl.edge.runtime import run_task
from step_rl.edge.site import LocalShopServer


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


def test_add_fault_is_one_shot():
    server = LocalShopServer(fault_add_once=True).start()
    try:
        get, post = _client(server)
        with pytest.raises(urllib.error.HTTPError) as error:
            get("/add/p3?qty=1")
        assert error.value.code == 500
        get("/add/p3?qty=1")
        state = urllib.request.urlopen(server.base_url + "/api/state")
        assert state.status == 200
    finally:
        server.stop()


def test_order_fault_is_one_shot():
    server = LocalShopServer(fault_order_once=True).start()
    try:
        get, post = _client(server)
        get("/add/p3?qty=1")
        get("/checkout")
        with pytest.raises(urllib.error.HTTPError) as error:
            post("/place-order", {"name": "A先生", "address": "深圳路1号"})
        assert error.value.code == 500
        get("/checkout")
        post("/place-order", {"name": "A先生", "address": "深圳路1号"})
    finally:
        server.stop()


def test_runtime_retries_transient_fault():
    pytest.importorskip("playwright")

    async def runner():
        server = LocalShopServer(fault_add_once=True).start()
        env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
        try:
            try:
                await env.start()
            except Exception as exc:  # pragma: no cover
                pytest.skip(f"browser unavailable: {exc}")
            result = await run_task(
                env,
                "买一件无线充电器并结算",
                None,
                None,
                skill_retries=1,
            )
            assert result["success"]
            assert len(result["attempts"]) == 2
        finally:
            await env.close()
            server.stop()

    asyncio.run(runner())
