"""AR021 skill outcome statistics, priority and demotion tests."""

from __future__ import annotations

import asyncio
import json

import pytest

from step_rl.edge.skill_stats import (
    all_skill_stats,
    clear_skill_stats,
    get_skill_stat,
    is_demoted,
    load_skill_stats,
    record_skill_outcome,
    save_skill_stats,
)
from step_rl.edge.skill_library import (
    clear_induced_skills,
    load_induced_skills,
    register_induced_skill,
    run_skill_hierarchy,
    save_induced_skills,
    skill_for_subtask,
)
from step_rl.edge.tasks import TaskSpec

# The four template steps of the real AR019 induced artifact
# (outputs/ar019/eval/induced_skills.json), reproduced verbatim.
GOOD_TEMPLATE = [
    {"kind": "type", "role": "", "name": "", "value": "2"},
    {"kind": "type", "role": "spinbutton", "name": "数量 {product}", "value": "1"},
    {"kind": "click", "role": "button", "name": "更新数量 {product}", "value": ""},
    {"kind": "click", "role": "button", "name": "移除 {product}", "value": ""},
]
STALE_TEMPLATE = [
    {"kind": "goto", "url": "/cart"},
    {"kind": "click", "role": "button", "name": "删除 {product}", "value": ""},
]


@pytest.fixture(autouse=True)
def _clean_registry_and_stats():
    clear_induced_skills()
    clear_skill_stats()
    yield
    clear_induced_skills()
    clear_skill_stats()


def _remove_task(pid: str = "p3", seed: int = 2) -> TaskSpec:
    return TaskSpec(
        task_id="rm",
        level=2,
        goal="把购物车中的商品移除",
        search_query="x",
        targets={pid: 0},
        operation="remove",
        predicates=["cart_without"],
        start_path="/cart",
        seed_cart={pid: seed},
    )


def _materialised_names() -> list:
    skill = skill_for_subtask(_remove_task())
    return [step.name for step in skill.steps] if skill is not None else None


# ---------------------------------------------------------------------------
# policy & statistics (pure logic)
# ---------------------------------------------------------------------------


def test_demotion_on_single_failure():
    record_skill_outcome("s1", "remove", False, note="element not found: 删除 x")
    stat = get_skill_stat("s1")
    assert stat.attempts == 1
    assert stat.success_rate == 0.0
    assert stat.demoted
    assert "0.00" in stat.demotion_reason
    assert is_demoted("s1")
    assert stat.last_failure_note == "element not found: 删除 x"
    assert stat.last_failure_at  # timestamp recorded


def test_demotion_policy_half_kept_third_failure_demos():
    record_skill_outcome("s2", "remove", True)
    record_skill_outcome("s2", "remove", False)
    stat = get_skill_stat("s2")
    assert stat.success_rate == 0.5
    assert not stat.demoted  # exactly 0.5 is kept (strict < policy)
    record_skill_outcome("s2", "remove", False)
    stat = get_skill_stat("s2")
    assert stat.attempts == 3
    assert stat.consecutive_failures == 2
    assert stat.demoted


def test_success_clears_consecutive_failures():
    record_skill_outcome("s3", "remove", False)
    record_skill_outcome("s3", "remove", False)
    record_skill_outcome("s3", "remove", True)
    stat = get_skill_stat("s3")
    assert stat.consecutive_failures == 0
    assert stat.last_success_at
    assert stat.success_rate == 1 / 3
    assert stat.demoted  # 0.33 < 0.5, demotion is sticky


def test_save_load_roundtrip(tmp_path):
    record_skill_outcome("a", "remove", True)
    record_skill_outcome("b", "remove", False, note="boom")
    record_skill_outcome("b", "remove", False)
    path = str(tmp_path / "stats.json")
    save_skill_stats(path)
    clear_skill_stats()
    assert all_skill_stats() == {}
    assert load_skill_stats(path) == ["a", "b"]
    stat_b = get_skill_stat("b")
    assert stat_b.attempts == 2
    assert stat_b.demoted
    assert stat_b.last_failure_note == "boom"
    assert not get_skill_stat("a").demoted
    # policy constants travel with the file
    data = json.loads(open(path, encoding="utf-8").read())
    assert data["policy"] == {"min_attempts": 1, "max_rate": 0.5}


# ---------------------------------------------------------------------------
# multi-candidate selection (priority & yielding)
# ---------------------------------------------------------------------------


def test_selection_untested_oldest_first():
    register_induced_skill("remove", GOOD_TEMPLATE, "cand_a")
    register_induced_skill("remove", STALE_TEMPLATE, "cand_b")
    # both untested (rate 0.0): registration order decides
    names = _materialised_names()
    assert names is not None
    assert any("更新数量 无线充电器" in name for name in names)  # GOOD_TEMPLATE
    assert not any("删除 无线充电器" in name for name in names)


def test_yield_after_demotion():
    register_induced_skill("remove", GOOD_TEMPLATE, "cand_a")
    register_induced_skill("remove", STALE_TEMPLATE, "cand_b")
    assert any("更新数量 无线充电器" in n for n in _materialised_names())
    record_skill_outcome("cand_a", "remove", False)  # stale evidence
    assert is_demoted("cand_a")
    names = _materialised_names()
    # cand_a demoted -> cand_b (untested) is now selected
    assert names is not None
    assert any("删除 无线充电器" in name for name in names)


def test_all_demoted_is_explicit_gap():
    register_induced_skill("remove", GOOD_TEMPLATE, "only")
    record_skill_outcome("only", "remove", False)
    assert skill_for_subtask(_remove_task()) is None


def test_proven_candidate_beats_untested():
    # cand_b registered first, cand_a second but already proven (1/1)
    register_induced_skill("remove", STALE_TEMPLATE, "cand_b")
    register_induced_skill("remove", GOOD_TEMPLATE, "cand_a")
    record_skill_outcome("cand_a", "remove", True)
    names = _materialised_names()
    assert any("更新数量 无线充电器" in n for n in names)
    assert not any("删除 无线充电器" in n for n in names)


def test_reregister_same_name_resets_stats():
    register_induced_skill("remove", STALE_TEMPLATE, "dup")
    record_skill_outcome("dup", "remove", False)
    assert is_demoted("dup")
    register_induced_skill("remove", GOOD_TEMPLATE, "dup")  # fresh trajectory
    assert not is_demoted("dup")
    stat = get_skill_stat("dup")
    assert stat is None or stat.attempts == 0
    names = _materialised_names()
    assert any("更新数量 无线充电器" in n for n in names)


# ---------------------------------------------------------------------------
# persistence compatibility (AR019/AR020 file shape)
# ---------------------------------------------------------------------------


def test_save_single_candidate_matches_legacy_shape(tmp_path):
    register_induced_skill("remove", GOOD_TEMPLATE, "induced_remove")
    path = str(tmp_path / "induced.json")
    save_induced_skills(path)
    data = json.loads(open(path, encoding="utf-8").read())
    assert data == {
        "remove": {"name": "induced_remove", "steps": GOOD_TEMPLATE}
    }
    # selected candidate is written; demoted-only operations are omitted
    register_induced_skill("remove", STALE_TEMPLATE, "stale_only")
    record_skill_outcome("induced_remove", "remove", False)  # demotes selected
    save_induced_skills(path)
    data = json.loads(open(path, encoding="utf-8").read())
    # induced_remove demoted; stale_only untested -> selected
    assert data["remove"]["name"] == "stale_only"


def test_load_legacy_artifact_shape(tmp_path):
    register_induced_skill("remove", GOOD_TEMPLATE, "induced_remove")
    path = str(tmp_path / "induced.json")
    save_induced_skills(path)
    clear_induced_skills()
    assert skill_for_subtask(_remove_task()) is None
    assert load_induced_skills(path) == ["remove"]
    skill = skill_for_subtask(_remove_task("p3", 2))
    assert skill is not None
    # prefix(1) + unit(3) x 1 product = 4 steps, as in AR019
    assert len(skill.steps) == 4
    assert skill.steps[3].name == "移除 无线充电器"


# ---------------------------------------------------------------------------
# real browser execution (Playwright + system Edge)
# ---------------------------------------------------------------------------


def test_real_success_recorded():
    pytest.importorskip("playwright")
    from step_rl.edge.browser import BrowserEnv
    from step_rl.edge.site import LocalShopServer
    from step_rl.edge.verifier import compute_progress

    register_induced_skill("remove", GOOD_TEMPLATE, "induced_remove")

    async def runner():
        server = LocalShopServer().start()
        env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
        try:
            try:
                await env.start()
            except Exception as exc:  # pragma: no cover
                pytest.skip(f"browser unavailable: {exc}")
            rollout = await run_skill_hierarchy(
                env, _remove_task(), None, None, fallback=False
            )
            assert rollout.success
            state = await env.get_state()
            assert state["cart"] == {}
            assert compute_progress(state, env.page_url_path, _remove_task()).success
        finally:
            await env.close()
            server.stop()

    asyncio.run(runner())
    stat = get_skill_stat("induced_remove")
    assert stat is not None
    assert stat.attempts == 1
    assert stat.successes == 1
    assert not stat.demoted


def test_real_stale_skill_yields():
    pytest.importorskip("playwright")
    from step_rl.edge.browser import BrowserEnv
    from step_rl.edge.site import LocalShopServer

    async def runner():
        server = LocalShopServer().start()
        env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
        try:
            await env.start()
        except Exception as exc:  # pragma: no cover
            pytest.skip(f"browser unavailable: {exc}")
            return
        try:
            # run 1: only the stale candidate exists -> real DOM failure
            register_induced_skill("remove", STALE_TEMPLATE, "stale")
            rollout1 = await run_skill_hierarchy(
                env, _remove_task(), None, None, fallback=False
            )
            assert not rollout1.success
            stale_stat = get_skill_stat("stale")
            assert stale_stat.attempts == 1
            assert stale_stat.failures == 1
            assert stale_stat.demoted
            assert "element not found" in stale_stat.last_failure_note
            # run 2: a good candidate is registered; the stale one must
            # yield (its attempt counter must stay frozen at 1)
            register_induced_skill("remove", GOOD_TEMPLATE, "induced_remove")
            rollout2 = await run_skill_hierarchy(
                env, _remove_task(), None, None, fallback=False
            )
            assert rollout2.success
            state = await env.get_state()
            assert state["cart"] == {}
            assert get_skill_stat("stale").attempts == 1
            good = get_skill_stat("induced_remove")
            assert good.attempts == 1
            assert good.successes == 1
        finally:
            await env.close()
            server.stop()

    asyncio.run(runner())
