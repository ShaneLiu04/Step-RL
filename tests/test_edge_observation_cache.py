"""AR025: real-Edge tests for the single-round-trip observation cache."""

from __future__ import annotations

import asyncio
import json

import pytest

from step_rl.edge.site import PRODUCTS, LocalShopServer
from step_rl.edge.tasks import TASK_BY_ID


async def _env_for(task_id: str):
    pytest.importorskip("playwright")
    from step_rl.edge.browser import BrowserEnv

    server = LocalShopServer().start()
    env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
    try:
        await env.start()
    except Exception as exc:  # pragma: no cover
        server.stop()
        pytest.skip(f"browser unavailable: {exc}")
    obs = await env.reset(TASK_BY_ID[task_id])
    return server, env, obs


def _fingerprint(obs):
    return json.dumps(
        {
            "url": obs.get("url"),
            "title": obs.get("title"),
            "text": obs.get("text"),
            "elements": obs.get("elements"),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


async def _single_roundtrip():
    server, env, obs = await _env_for("sft_search_p1")
    try:
        metrics = env.observation_metrics
        assert metrics["calls"] == 1
        assert metrics["dom_scans"] == 1
        assert metrics["roundtrips"] == 2
        assert obs["elements"]
    finally:
        await env.close()
        server.stop()


def test_single_roundtrip_snapshot():
    asyncio.run(_single_roundtrip())


async def _cache_hit_and_live_state():
    server, env, obs = await _env_for("sft_search_p1")
    try:
        before = _fingerprint(obs)
        metrics = env.observation_metrics
        scans_before = metrics["dom_scans"]
        hits_before = metrics["hits"]
        again = await env.observe()
        assert env.observation_metrics["hits"] == hits_before + 1
        assert env.observation_metrics["dom_scans"] == scans_before
        assert _fingerprint(again) == before
        assert again["state"]["cart"] == obs["state"]["cart"]
    finally:
        await env.close()
        server.stop()


def test_unchanged_observation_hits_cache():
    asyncio.run(_cache_hit_and_live_state())


async def _dom_change_invalidates():
    server, env, obs = await _env_for("sft_search_p1")
    try:
        names = {product.name for product in PRODUCTS.values()}
        link = next(
            e
            for e in obs["elements"]
            if e["role"] == "link" and e["accessible_name"] in names
        )
        metrics = env.observation_metrics
        misses_before = metrics["misses"]
        assert (
            await env.execute({"action": "click", "params": {"element": link["eid"]}})
        )["ok"]
        after = await env.observe()
        assert env.observation_metrics["misses"] > misses_before
        assert "/product/" in after["url"]
        assert _fingerprint(after) != _fingerprint(obs)
    finally:
        await env.close()
        server.stop()


def test_dom_change_invalidates_cache():
    asyncio.run(_dom_change_invalidates())


async def _type_invalidates_value():
    server, env, obs = await _env_for("sft_search_p1")
    try:
        box = next(e for e in obs["elements"] if e["role"] == "textbox")
        metrics = env.observation_metrics
        misses_before = metrics["misses"]
        assert (
            await env.execute(
                {
                    "action": "type",
                    "params": {"element": box["eid"], "text": "iphone"},
                }
            )
        )["ok"]
        after = await env.observe()
        assert env.observation_metrics["misses"] > misses_before
        updated = next(e for e in after["elements"] if e["role"] == "textbox")
        assert updated["value"] == "iphone"
    finally:
        await env.close()
        server.stop()


def test_type_invalidates_cached_value():
    asyncio.run(_type_invalidates_value())


async def _force_bypasses_cache():
    server, env, obs = await _env_for("sft_search_p1")
    try:
        scans_before = env.observation_metrics["dom_scans"]
        await env.observe()
        assert env.observation_metrics["dom_scans"] == scans_before
        forced = await env.observe(force=True)
        assert env.observation_metrics["dom_scans"] == scans_before + 1
        assert forced["elements"] == obs["elements"]
    finally:
        await env.close()
        server.stop()


def test_force_bypasses_cache():
    asyncio.run(_force_bypasses_cache())


async def _skill_reuses_initial_observation():
    pytest.importorskip("playwright")
    from step_rl.edge.skill_library import run_skill, search_skill

    server, env, obs = await _env_for("sft_search_p1")
    try:
        calls_before = env.observation_metrics["calls"]
        result = await run_skill(env, search_skill("iphone"), initial_obs=obs)
        assert result.success
        assert result.observation is not None
        # goto/type/click: one post-action observation each; no extra initial one.
        assert env.observation_metrics["calls"] == calls_before + 3
        state = await env.get_state()
        assert state["query"] == "iphone"
    finally:
        await env.close()
        server.stop()


def test_skill_reuses_initial_observation():
    asyncio.run(_skill_reuses_initial_observation())
