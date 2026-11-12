"""AR020 multi-product batch removal tests (planner, materialisation, induction)."""

from __future__ import annotations

import asyncio

import pytest

from step_rl.edge.browser import BrowserEnv
from step_rl.edge.planner import fetch_catalog, plan_instruction
from step_rl.edge.site import LocalShopServer
from step_rl.edge.skill_induction import (
    RecordedStep,
    collapse_repeated_product_steps,
    induce_batch_template,
    induce_skill,
)
from step_rl.edge.skill_library import (
    clear_induced_skills,
    register_induced_skill,
    run_skill_hierarchy,
    skill_for_subtask,
)
from step_rl.edge.tasks import TaskSpec
from step_rl.edge.verifier import compute_progress

BATCH_INSTRUCTION = "把无线充电器和蓝牙降噪耳机从购物车移除"

# The four template steps of the real AR019 induced artifact
# (outputs/ar019/eval/induced_skills.json), reproduced verbatim.
AR019_TEMPLATE = [
    {"kind": "type", "role": "", "name": "", "value": "2"},
    {"kind": "type", "role": "spinbutton", "name": "数量 {product}", "value": "1"},
    {"kind": "click", "role": "button", "name": "更新数量 {product}", "value": ""},
    {"kind": "click", "role": "button", "name": "移除 {product}", "value": ""},
]


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_induced_skills()
    yield
    clear_induced_skills()


def _remove_task(targets: dict, seeds: dict | None = None, tid: str = "rm") -> TaskSpec:
    return TaskSpec(
        task_id=tid,
        level=2,
        goal=BATCH_INSTRUCTION,
        search_query="x",
        targets=targets,
        operation="remove",
        predicates=["cart_without"],
        start_path="/cart",
        seed_cart=seeds if seeds is not None else {pid: 1 for pid in targets},
    )


def test_planner_batch_remove_keeps_all_products():
    server = LocalShopServer().start()
    try:
        catalog = fetch_catalog(server.base_url)
        spec = plan_instruction(BATCH_INSTRUCTION, catalog)
        assert spec is not None
        assert spec.operation == "remove"
        assert spec.predicates == ["cart_without"]
        assert spec.start_path == "/cart"
        assert spec.targets == {"p3": 0, "p4": 0}
        assert spec.seed_cart == {"p3": 1, "p4": 1}
    finally:
        server.stop()


def test_planner_single_remove_unchanged():
    server = LocalShopServer().start()
    try:
        catalog = fetch_catalog(server.base_url)
        spec = plan_instruction("把购物车中的无线充电器移除", catalog)
        assert spec is not None
        assert spec.targets == {"p3": 0}
        assert spec.seed_cart == {"p3": 1}
        assert spec.operation == "remove"
    finally:
        server.stop()


def test_induce_batch_template_collapses_two_clicks():
    server = LocalShopServer().start()
    try:
        catalog = fetch_catalog(server.base_url)
        task = _remove_task({"p3": 0, "p4": 0})
        records = [
            RecordedStep(kind="goto", url="/cart"),
            RecordedStep(kind="click", role="button", name="移除 无线充电器"),
            RecordedStep(kind="click", role="button", name="移除 蓝牙降噪耳机"),
        ]
        template = induce_batch_template(task, records, catalog)
        assert template is not None
        assert len(template["steps"]) == 2
        assert template["steps"][0] == {"kind": "goto", "url": "/cart"}
        clicks = [s for s in template["steps"] if s["kind"] == "click"]
        assert len(clicks) == 1
        assert clicks[0]["name"] == "移除 {product}"
    finally:
        server.stop()


def test_induce_batch_template_ar019_shape():
    """The real AR019 per-product pattern (stray type, qty, update, remove)."""
    server = LocalShopServer().start()
    try:
        catalog = fetch_catalog(server.base_url)
        task = _remove_task({"p3": 0, "p4": 0})
        records = [
            RecordedStep(kind="type", role="", name="", value="2"),
            RecordedStep(
                kind="type", role="spinbutton", name="数量 无线充电器", value="1"
            ),
            RecordedStep(kind="click", role="button", name="更新数量 无线充电器"),
            RecordedStep(kind="click", role="button", name="移除 无线充电器"),
            RecordedStep(
                kind="type", role="spinbutton", name="数量 蓝牙降噪耳机", value="1"
            ),
            RecordedStep(kind="click", role="button", name="更新数量 蓝牙降噪耳机"),
            RecordedStep(kind="click", role="button", name="移除 蓝牙降噪耳机"),
        ]
        template = induce_batch_template(task, records, catalog)
        assert template is not None
        assert [s["name"] for s in template["steps"]] == [
            "",
            "数量 {product}",
            "更新数量 {product}",
            "移除 {product}",
        ]
    finally:
        server.stop()


def test_induce_batch_template_real_p1_shape():
    """The real P1 trajectory: stray type, update+remove p3, bare remove p2.

    The blocks are prefix-monotone (not identical); the per-product unit
    must be their longest common suffix, ending at 移除 {product}.
    """
    server = LocalShopServer().start()
    try:
        catalog = fetch_catalog(server.base_url)
        task = _remove_task({"p3": 0, "p2": 0})
        records = [
            RecordedStep(kind="type", role="", name="", value="2"),
            RecordedStep(kind="click", role="button", name="更新数量 无线充电器"),
            RecordedStep(kind="click", role="button", name="移除 无线充电器"),
            RecordedStep(kind="click", role="button", name="移除 USB-C 快充数据线"),
        ]
        template = induce_batch_template(task, records, catalog)
        assert template is not None
        assert [s["name"] for s in template["steps"]] == ["", "移除 {product}"]
    finally:
        server.stop()


def test_induce_batch_template_common_suffix_only():
    server = LocalShopServer().start()
    try:
        catalog = fetch_catalog(server.base_url)
        task = _remove_task({"p3": 0, "p4": 0})
        # p3 block: qty+update+remove; p4 block: qty+remove -> unit = [移除]
        records = [
            RecordedStep(
                kind="type", role="spinbutton", name="数量 无线充电器", value="1"
            ),
            RecordedStep(kind="click", role="button", name="更新数量 无线充电器"),
            RecordedStep(kind="click", role="button", name="移除 无线充电器"),
            RecordedStep(
                kind="type", role="spinbutton", name="数量 蓝牙降噪耳机", value="1"
            ),
            RecordedStep(kind="click", role="button", name="移除 蓝牙降噪耳机"),
        ]
        template = induce_batch_template(task, records, catalog)
        assert template is not None
        assert [s["name"] for s in template["steps"]] == ["移除 {product}"]
    finally:
        server.stop()


def test_induce_batch_template_single_target_returns_none():
    server = LocalShopServer().start()
    try:
        catalog = fetch_catalog(server.base_url)
        task = _remove_task({"p3": 0})
        records = [RecordedStep(kind="click", role="button", name="移除 无线充电器")]
        assert induce_batch_template(task, records, catalog) is None
    finally:
        server.stop()


def test_induce_single_product_is_no_op():
    server = LocalShopServer().start()
    try:
        catalog = fetch_catalog(server.base_url)
        task = _remove_task({"p3": 0})
        records = [
            RecordedStep(kind="goto", url="/cart"),
            RecordedStep(kind="click", role="button", name="移除 无线充电器"),
        ]
        template = induce_skill(task, records, catalog)
        # no consecutive identical step existed, so collapse changed nothing
        raw = [
            {"kind": "goto", "url": "/cart"},
            {"kind": "click", "role": "button", "name": "移除 {product}", "value": ""},
        ]
        assert collapse_repeated_product_steps(raw) == raw
        assert len(template["steps"]) == 2
    finally:
        server.stop()


def test_materialize_multi_target_expands_unit():
    register_induced_skill("remove", AR019_TEMPLATE, "induced_remove")
    task = _remove_task({"p3": 0, "p4": 0}, {"p3": 2, "p4": 3})
    skill = skill_for_subtask(task)
    assert skill is not None
    assert skill.name == "induced_remove"
    # prefix(1) + unit(3) x 2 products + suffix(0) = 7 steps
    assert len(skill.steps) == 7
    assert skill.steps[0].value == "2"
    assert skill.steps[1].name == "数量 无线充电器"
    assert skill.steps[2].name == "更新数量 无线充电器"
    assert skill.steps[3].name == "移除 无线充电器"
    assert skill.steps[4].name == "数量 蓝牙降噪耳机"
    assert skill.steps[5].name == "更新数量 蓝牙降噪耳机"
    assert skill.steps[6].name == "移除 蓝牙降噪耳机"


def test_materialize_single_target_matches_old():
    register_induced_skill("remove", AR019_TEMPLATE, "induced_remove")
    skill = skill_for_subtask(_remove_task({"p3": 0}, {"p3": 2}))
    assert skill is not None
    assert len(skill.steps) == 4
    assert skill.steps[0].value == "2"
    assert skill.steps[1].name == "数量 无线充电器"
    assert skill.steps[2].name == "更新数量 无线充电器"
    assert skill.steps[3].name == "移除 无线充电器"


def test_skill_for_subtask_batch_not_none():
    register_induced_skill("remove", AR019_TEMPLATE, "induced_remove")
    assert skill_for_subtask(_remove_task({"p3": 0, "p4": 0})) is not None


def test_cart_without_multi_target():
    task = _remove_task({"p3": 0, "p4": 0})
    assert compute_progress({"cart": {}}, "/cart", task).success
    assert not compute_progress({"cart": {"p4": 1}}, "/cart", task).success
    assert not compute_progress({"cart": {"p3": 2}}, "/cart", task).success


def test_batch_remove_real_browser():
    pytest.importorskip("playwright")

    register_induced_skill(
        "remove",
        [{"kind": "click", "role": "button", "name": "移除 {product}"}],
        "induced_remove",
    )
    task = _remove_task({"p3": 0, "p4": 0}, {"p3": 2, "p4": 3}, tid="batch_rm")

    async def runner():
        server = LocalShopServer().start()
        env = BrowserEnv(server, channel="msedge", headless=True, semantic=True)
        try:
            try:
                await env.start()
            except Exception as exc:  # pragma: no cover
                pytest.skip(f"browser unavailable: {exc}")
            rollout = await run_skill_hierarchy(env, task, None, None, fallback=False)
            assert rollout.success
            state = await env.get_state()
            assert state["cart"] == {}
        finally:
            await env.close()
            server.stop()

    asyncio.run(runner())
