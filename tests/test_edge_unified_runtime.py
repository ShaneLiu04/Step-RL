"""AR011 unified runtime composition tests (real browser, no LLM needed)."""

from __future__ import annotations

import asyncio

import pytest

from step_rl.edge.browser import BrowserEnv
from step_rl.edge.runtime import run_task
from step_rl.edge.site import LocalShopServer


def test_runtime_uses_skill_without_llm():
    pytest.importorskip("playwright")

    async def runner():
        server = LocalShopServer().start()
        env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
        try:
            try:
                await env.start()
            except Exception as exc:  # pragma: no cover
                pytest.skip(f"browser unavailable: {exc}")
            result = await run_task(env, "买1件无线充电器", None, None)
            assert result["success"]
            assert result["fallback"] is False
            assert all(step.source == "skill" for step in result["steps"])
        finally:
            await env.close()
            server.stop()

    asyncio.run(runner())


def test_runtime_replans_dynamic_stock():
    pytest.importorskip("playwright")

    async def runner():
        server = LocalShopServer(checkout_stock_drop={"p4": 1}).start()
        env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
        try:
            try:
                await env.start()
            except Exception as exc:  # pragma: no cover
                pytest.skip(f"browser unavailable: {exc}")
            result = await run_task(
                env,
                "买两件蓝牙耳机；如果缺货，就买两件USB-C数据线，并结算",
                None,
                None,
            )
            assert result["success"]
            assert len(result["attempts"]) == 2
            assert result["spec"] == {"p2": 2}
        finally:
            await env.close()
            server.stop()

    asyncio.run(runner())
