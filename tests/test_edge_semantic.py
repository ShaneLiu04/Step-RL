"""Semantic Set-of-Mark interface tests (unit + real browser smoke)."""

from __future__ import annotations

import asyncio

import pytest

from step_rl.edge.expert import _to_semantic
from step_rl.edge.policy import build_prompt
from step_rl.edge.tasks import TASK_BY_ID


def test_selector_to_element_conversion():
    action = {"action": "click", "params": {"selector": "#search-btn"}}
    elements = [
        {"selector": "#q", "eid": "e1"},
        {"selector": "#search-btn", "eid": "e2"},
    ]
    converted = _to_semantic(action, elements)
    assert converted["params"] == {"element": "e2"}


def test_goto_is_not_converted():
    action = {"action": "goto", "params": {"url": "/cart"}}
    assert _to_semantic(action, []) == action


def test_semantic_prompt_hides_selectors():
    prompt = build_prompt(
        "任务",
        {
            "url": "/",
            "title": "首页",
            "elements": [
                {
                    "eid": "e1",
                    "selector": "#q",
                    "tag": "input",
                    "role": "textbox",
                    "accessible_name": "搜索商品",
                }
            ],
            "state": {},
        },
        semantic=True,
    )
    assert "e1" in prompt
    assert "搜索商品" in prompt
    assert "#q" not in prompt
    assert '"element"' in prompt


async def _semantic_action_survives_id_churn():
    pytest.importorskip("playwright")
    from step_rl.edge.browser import BrowserEnv
    from step_rl.edge.site import LocalShopServer

    server = LocalShopServer().start()
    env = BrowserEnv(
        server, channel="msedge", headless=True, semantic=True, perturb_ids=True
    )
    try:
        try:
            await env.start()
        except Exception as exc:  # pragma: no cover - environment dependent
            pytest.skip(f"browser unavailable: {exc}")
        obs = await env.reset(TASK_BY_ID["sft_search_p1"])
        # ids were randomized after the observation snapshot
        assert await env._page.evaluate("() => document.querySelector('#q')") is None
        search_input = next(
            e
            for e in obs["elements"]
            if e["role"] == "textbox" and "搜索" in e["accessible_name"]
        )
        result = await env.execute(
            {
                "action": "type",
                "params": {"element": search_input["eid"], "text": "iphone"},
            }
        )
        assert result["ok"], result
        obs = await env.observe()
        button = next(
            e
            for e in obs["elements"]
            if e["role"] == "button" and "搜索" in e["accessible_name"]
        )
        result = await env.execute(
            {"action": "click", "params": {"element": button["eid"]}}
        )
        assert result["ok"], result
        state = await env.get_state()
        assert state["query"] == "iphone"
    finally:
        await env.close()
        server.stop()


def test_semantic_action_survives_id_churn():
    asyncio.run(_semantic_action_survives_id_churn())
