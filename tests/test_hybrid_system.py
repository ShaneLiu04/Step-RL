"""AR033: HybridSystem real local path and remote isolation contract."""

from __future__ import annotations

import asyncio

import pytest

from step_rl.edge.adapters.base import Observation
from step_rl.edge.system import HybridSystem


def test_hybrid_local_deterministic():
    async def run():
        system = HybridSystem()
        try:
            result = await system.run_local("买两件无线充电器")
        except Exception as exc:  # pragma: no cover
            if any(
                key in str(exc).lower()
                for key in ("msedge", "browser", "playwright", "executable")
            ):
                pytest.skip(f"browser unavailable: {exc}")
            raise
        assert result["success"]
        assert result["policy_steps"] == 0
        assert result["prompt_tokens"] == 0
        assert result["cart"] == {"p3": 2}
        assert result["screenshot_bytes"] > 0

    asyncio.run(run())


def test_hybrid_rejects_unknown_site():
    async def run():
        system = HybridSystem()
        with pytest.raises(ValueError):
            await system.run_remote("unknown", "x")

    asyncio.run(run())


class _StubAdapter:
    def __init__(self, *, fail: bool = False, links=None, blocked: str = ""):
        self.fail = fail
        self.links = [] if links is None else links
        self.blocked = blocked

    async def open_session(self, **_kwargs):
        return None

    async def close(self):
        return None

    async def search(self, _query):
        if self.fail:
            raise RuntimeError("network timeout")
        return Observation(
            url="https://example.invalid/search",
            title="stub search",
            page_type="search",
            signals={"blocked": self.blocked},
        )

    async def product_links(self):
        return self.links


def test_hybrid_remote_exception_is_isolated(monkeypatch):
    import step_rl.edge.system as system_module

    monkeypatch.setattr(
        system_module, "create_adapter", lambda site, **kwargs: _StubAdapter(fail=True)
    )
    result = asyncio.run(HybridSystem().run_remote("jd", "x"))
    assert result["ok"] is False
    assert "RuntimeError: network timeout" in result["error"]


def test_hybrid_remote_empty_links_is_failure(monkeypatch):
    import step_rl.edge.system as system_module

    monkeypatch.setattr(
        system_module, "create_adapter", lambda site, **kwargs: _StubAdapter(links=[])
    )
    result = asyncio.run(HybridSystem().run_remote("jd", "x"))
    assert result["ok"] is False
    assert "no product links" in result["error"]


def test_hybrid_remote_blocked_is_failure(monkeypatch):
    import step_rl.edge.system as system_module

    monkeypatch.setattr(
        system_module,
        "create_adapter",
        lambda site, **kwargs: _StubAdapter(links=["u"], blocked="login_required"),
    )
    result = asyncio.run(HybridSystem().run_remote("taobao", "x"))
    assert result["ok"] is False
    assert result["blocked"] == "login_required"
