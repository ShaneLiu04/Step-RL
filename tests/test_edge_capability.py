"""AR012 capability gating tests."""

from __future__ import annotations

import asyncio

from step_rl.edge.browser import BrowserEnv
from step_rl.edge.capability import check_capability
from step_rl.edge.planner import fetch_catalog
from step_rl.edge.runtime import run_task
from step_rl.edge.site import LocalShopServer


def test_capability_manifest():
    server = LocalShopServer().start()
    try:
        catalog = fetch_catalog(server.base_url)
        assert check_capability("买两件USB-C数据线并结算", catalog).covered
        assert not check_capability("帮我写一首诗", catalog).covered
    finally:
        server.stop()


def test_unsupported_returns_fallback_required():
    server = LocalShopServer().start()
    env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
    try:
        result = asyncio.run(run_task(env, "帮我写一首诗", None, None))
        assert result["success"] is False
        assert result["fallback_required"] is True
        assert result["steps"] == []
    finally:
        server.stop()
