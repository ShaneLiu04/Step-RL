"""AR010 skill compilation tests."""

from __future__ import annotations

import asyncio

import pytest

from step_rl.edge.skill_library import (
    SkillStep,
    add_item_skill,
    checkout_skill,
    search_skill,
    skill_for_subtask,
)
from step_rl.edge.tasks import TASK_BY_ID


def test_skills_are_parameterised():
    search = search_skill("蓝牙")
    assert any(step.value == "蓝牙" for step in search.steps)
    add = add_item_skill("p4", 2)
    assert any(step.value == "2" for step in add.steps)
    assert any(step.name.startswith("蓝牙") for step in add.steps)
    checkout = checkout_skill()
    assert any(step.name == "提交订单" for step in checkout.steps)


def test_skill_for_subtask():
    assert skill_for_subtask(TASK_BY_ID["ev_search_p3"]).name == "search"
    assert skill_for_subtask(TASK_BY_ID["ev_qty_p3"]).name == "add_item"
    assert skill_for_subtask(TASK_BY_ID["ev_checkout_p3"]).name == "checkout"


def test_skill_step_requires_known_roles():
    step = SkillStep("click", name="搜索", role="button")
    assert step.role == "button"


def test_real_browser_skill_execution():
    pytest.importorskip("playwright")
    from step_rl.edge.browser import BrowserEnv
    from step_rl.edge.site import LocalShopServer
    from step_rl.edge.skill_library import run_skill_hierarchy

    async def runner():
        server = LocalShopServer().start()
        env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
        try:
            try:
                await env.start()
            except Exception as exc:  # pragma: no cover
                pytest.skip(f"browser unavailable: {exc}")
            rollout = await run_skill_hierarchy(
                env,
                TASK_BY_ID["ev_add_p3"],
                None,
                None,
                fallback=False,
            )
            assert rollout.success
            assert all(step.source == "skill" for step in rollout.steps)
        finally:
            await env.close()
            server.stop()

    asyncio.run(runner())
