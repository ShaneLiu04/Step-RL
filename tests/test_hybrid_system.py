"""AR033: HybridSystem real local path and remote isolation contract."""

from __future__ import annotations

import asyncio

import pytest

from step_rl.system import HybridSystem


def test_hybrid_local_deterministic():
    async def run():
        system = HybridSystem()
        result = await system.run_local("买两件无线充电器")
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
