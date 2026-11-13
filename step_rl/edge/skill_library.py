"""Parameterised skills compiled from successful expert action patterns.

Skills execute against the real DOM through semantic names; they do not call
the language model.  A failed skill falls back to the regular LLM hierarchy.

AR019 adds an induced-skill registry: successful LLM-fallback trajectories
are generalised into parameterised templates (``{product}`` / ``{qty}``
placeholders), registered here and persisted as JSON, so later tasks of the
same operation run with zero LLM calls.

AR021 upgrades the registry to multiple candidates per operation with
real execution statistics: every skill run records its
verifier-confirmed outcome into :mod:`skill_stats`; selection prefers the
higher real success rate, and a skill whose observed rate proves it bad
is demoted (yields to a better candidate or to the explicit capability
gap + LLM fallback).
"""

from __future__ import annotations

import itertools
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from .browser import BrowserEnv
from .hierarchical import adapter_for_subtask, decompose_task
from .rollout import Rollout, StepRecord, rollout_task
from .site import PRODUCTS
from .skill_stats import (
    is_demoted,
    rank_candidates,
    record_skill_outcome,
    reset_skill_stats,
)
from .tasks import TaskSpec
from .verifier import compute_progress

NAME_VALUE = "刘星言先生"
ADDRESS_VALUE = "深圳市龙岗区坂田路1号"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


# operation -> [candidate {"name", "steps", "order", "registered_at"}]
# AR021: multiple candidates may coexist per operation; selection by real
# success rate (see skill_stats), demoted candidates yield.
_INDUCED: Dict[str, List[Dict[str, Any]]] = {}
_ORDER = itertools.count(1)


def register_induced_skill(
    operation: str,
    template: List[Dict[str, Any]],
    name: str = "",
) -> None:
    """Register (upsert) an induced skill template for ``operation``.

    AR021: candidates are keyed by name.  Re-registering an existing name
    replaces its steps and resets its execution statistics (a fresh
    trajectory is fresh evidence - the self-healing closed loop); a new
    name appends a candidate after the existing ones.
    """

    candidate_name = name or f"induced_{operation}"
    candidates = _INDUCED.setdefault(operation, [])
    for candidate in candidates:
        if candidate["name"] == candidate_name:
            candidate["steps"] = [dict(step) for step in template]
            candidate["registered_at"] = _now_iso()
            reset_skill_stats(candidate_name)
            return
    candidates.append(
        {
            "name": candidate_name,
            "steps": [dict(step) for step in template],
            "order": next(_ORDER),
            "registered_at": _now_iso(),
        }
    )


def induced_candidates(operation: str) -> List[Dict[str, Any]]:
    """Read-only copy of the candidate list for ``operation``."""

    return [dict(candidate) for candidate in _INDUCED.get(operation, [])]


def _select_best(operation: str) -> Optional[Dict[str, Any]]:
    """Pick the candidate to materialise (AR021 selection rule).

    Demoted candidates are skipped entirely; among the rest, higher real
    success rate wins (untested counts as 0.0), ties keep registration
    order.  When every candidate is demoted, ``None`` is returned - the
    explicit capability gap that hands the task back to the LLM fallback
    (AR019 semantics).
    """

    candidates = _INDUCED.get(operation, [])
    if not candidates:
        return None
    ordered = sorted(candidates, key=lambda c: c["order"])
    eligible = [c for c in ordered if not is_demoted(c["name"])]
    if not eligible:
        return None
    by_name = {c["name"]: c for c in eligible}
    return by_name[rank_candidates([c["name"] for c in eligible])[0]]


def clear_induced_skills() -> None:
    _INDUCED.clear()


def induced_operations() -> List[str]:
    return sorted(_INDUCED)


def save_induced_skills(path: str) -> None:
    """Persist the selected candidate of each operation.

    File shape stays the AR019/AR020 one (``{"op": {"name", "steps"}}``):
    with a single candidate it is field-for-field identical to the old
    output.  Operations whose candidates are all demoted are omitted -
    the file honestly states that no usable skill exists for them.
    """

    data: Dict[str, Any] = {}
    for operation in _INDUCED:
        best = _select_best(operation)
        if best is None:
            continue
        data[operation] = {
            "name": best["name"],
            "steps": [dict(step) for step in best["steps"]],
        }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def load_induced_skills(path: str) -> List[str]:
    """Load and register persisted induced-skill templates."""

    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    for operation, entry in data.items():
        register_induced_skill(operation, entry.get("steps", []), entry.get("name", ""))
    return sorted(data)


def _placeholder_product(step: Dict[str, Any]) -> bool:
    return (
        "{product}" in str(step.get("name", ""))
        or "{product}" in str(step.get("value", ""))
    )


def _split_product_unit(steps: List[Dict[str, Any]]):
    """Split template steps into ``(prefix, unit, suffix)``.

    The *unit* is the maximal run of ``{product}`` steps starting at the
    first such step; everything before it (page setup such as
    ``goto /cart``) belongs to the prefix and runs once, everything after
    the suffix (runs once).  Templates without any ``{product}`` step
    degenerate to ``(steps, [], [])``.
    """

    first = next((i for i, item in enumerate(steps) if _placeholder_product(item)), None)
    if first is None:
        return list(steps), [], []
    end = first
    while end < len(steps) and _placeholder_product(steps[end]):
        end += 1
    return steps[:first], steps[first:end], steps[end:]


def _instantiate(step: Dict[str, Any], pid: str, qty: int) -> "SkillStep":
    """Resolve ``{product}``/``{qty}`` in one template step for ``pid``."""

    product = PRODUCTS.get(pid) if pid else None
    name = str(step.get("name", ""))
    value = str(step.get("value", ""))
    if product is not None:
        name = name.replace("{product}", product.name)
        value = value.replace("{product}", product.name)
    value = value.replace("{qty}", str(qty))
    return SkillStep(
        kind=str(step.get("kind", "")),
        name=name,
        role=str(step.get("role", "")),
        value=value,
        url=str(step.get("url", "")),
    )


def _materialize(entry: Dict[str, Any], task: TaskSpec) -> Skill:
    """Instantiate a template for ``task`` by resolving placeholders.

    AR020 multi-target expansion: the template is ``prefix + unit +
    suffix`` where the unit references ``{product}``; the unit is
    instantiated once per target pid (``task.targets`` insertion order),
    prefix and suffix once.  A single-target task yields exactly the step
    sequence of the original first-pid-only implementation.
    """

    pids = list(task.targets)
    steps: List[SkillStep] = []
    if not pids:
        for item in entry.get("steps", []):
            steps.append(_instantiate(item, "", 1))
        return Skill(str(entry.get("name", "induced")), steps)
    first_pid = pids[0]
    prefix, unit, suffix = _split_product_unit(list(entry.get("steps", [])))
    for item in prefix:
        steps.append(_instantiate(item, first_pid, task.targets[first_pid]))
    for pid in pids:
        for item in unit:
            steps.append(_instantiate(item, pid, task.targets[pid]))
    for item in suffix:
        steps.append(_instantiate(item, first_pid, task.targets[first_pid]))
    return Skill(str(entry.get("name", "induced")), steps)


@dataclass(frozen=True)
class SkillStep:
    kind: str  # goto / type / click
    name: str = ""
    role: str = ""
    value: str = ""
    url: str = ""


@dataclass
class Skill:
    name: str
    steps: List[SkillStep] = field(default_factory=list)


@dataclass
class SkillResult:
    success: bool
    actions: List[Dict[str, Any]] = field(default_factory=list)
    error: str = ""


def search_skill(query: str) -> Skill:
    return Skill(
        "search",
        [
            SkillStep("goto", url="/"),
            SkillStep("type", name="搜索商品", role="textbox", value=query),
            SkillStep("click", name="搜索", role="button"),
        ],
    )


def add_item_skill(pid: str, qty: int) -> Skill:
    product = PRODUCTS[pid]
    query = product.keywords[0] if product.keywords else product.name
    return Skill(
        "add_item",
        [
            SkillStep("goto", url="/"),
            SkillStep("type", name="搜索商品", role="textbox", value=query),
            SkillStep("click", name="搜索", role="button"),
            SkillStep("click", name=product.name, role="link"),
            SkillStep("type", name="数量", role="spinbutton", value=str(qty)),
            SkillStep("click", name="加入购物车", role="button"),
        ],
    )


def update_quantity_skill(pid: str, qty: int) -> Skill:
    product = PRODUCTS[pid]
    return Skill(
        "update_quantity",
        [
            SkillStep("goto", url="/cart"),
            SkillStep(
                "type",
                name=product.name,
                role="spinbutton",
                value=str(qty),
            ),
            SkillStep(
                "click",
                name=f"更新数量 {product.name}",
                role="button",
            ),
        ],
    )


def checkout_skill() -> Skill:
    return Skill(
        "checkout",
        [
            SkillStep("goto", url="/checkout"),
            SkillStep("type", name="收货人", role="textbox", value=NAME_VALUE),
            SkillStep("type", name="地址", role="textbox", value=ADDRESS_VALUE),
            SkillStep("click", name="提交订单", role="button"),
        ],
    )


def skill_for_subtask(task: TaskSpec) -> Optional[Skill]:
    if task.operation == "update":
        pid = next(iter(task.targets), None)
        if pid:
            return update_quantity_skill(pid, task.targets[pid])
        return None
    if task.operation in _INDUCED:
        best = _select_best(task.operation)
        if best is None:
            # Every candidate is demoted: explicit capability gap, never
            # silently route to a broken template or to the add-item skill.
            return None
        return _materialize(best, task)
    if task.operation not in ("add", ""):
        # Unregistered non-add operations are an explicit capability gap:
        # never silently route them to the add-item skill.
        return None
    if task.level == 1:
        return search_skill(task.search_query)
    if task.require_checkout:
        return checkout_skill()
    pid = next(iter(task.targets), None)
    if pid:
        return add_item_skill(pid, task.targets[pid])
    return None


def _find(elements: List[Dict[str, Any]], step: SkillStep) -> Optional[Dict[str, Any]]:
    candidates = []
    for element in elements:
        if step.role and element.get("role") != step.role:
            continue
        name = element.get("accessible_name", "")
        if step.name and step.name.lower() not in name.lower():
            continue
        if any(word in name for word in ("推荐", "广告", "赞助")):
            continue
        candidates.append(element)
    if not candidates:
        return None
    for element in candidates:
        if element.get("accessible_name", "").strip().lower() == step.name.lower():
            return element
    return candidates[0]


async def run_skill(env: BrowserEnv, skill: Skill) -> SkillResult:
    obs = await env.observe()
    actions: List[Dict[str, Any]] = []
    for step in skill.steps:
        if step.kind == "goto":
            action = {"action": "goto", "params": {"url": step.url}}
        else:
            element = _find(obs.get("elements", []), step)
            if element is None and step.role == "spinbutton":
                element = next(
                    (
                        candidate
                        for candidate in obs.get("elements", [])
                        if candidate.get("role") == "spinbutton"
                    ),
                    None,
                )
            if element is None:
                return SkillResult(False, actions, f"element not found: {step.name}")
            params = {"element": element["eid"]}
            if step.kind == "type":
                params["text"] = step.value
            action = {"action": step.kind, "params": params}
        result = await env.execute(action)
        actions.append(action)
        if not result.get("ok"):
            return SkillResult(False, actions, str(result.get("error", "")))
        obs = await env.observe()
    return SkillResult(True, actions)


async def run_skill_hierarchy(
    env: BrowserEnv,
    task: TaskSpec,
    model,
    tokenizer,
    *,
    fallback: bool = True,
    semantic: bool = True,
    max_steps_per_subtask: int = 12,
    reset: bool = True,
) -> Rollout:
    obs = await env.reset(task) if reset else await env.observe()
    steps: List[StepRecord] = []
    for subtask in decompose_task(task):
        adapter = adapter_for_subtask(subtask)
        if hasattr(model, "set_adapter"):
            model.set_adapter(adapter)
        skill = skill_for_subtask(subtask)
        ok = False
        if skill is not None:
            result = await run_skill(env, skill)
            for action in result.actions:
                steps.append(
                    StepRecord(
                        prompt="skill",
                        prompt_ids=[],
                        response_ids=[],
                        old_logprobs=[],
                        response_text="",
                        action=action,
                        exec_ok=True,
                        error="",
                        phi_before=0.0,
                        phi_after=0.0,
                        source="skill",
                    )
                )
            obs = await env.observe()
            ok = compute_progress(obs["state"], obs["url"], subtask).success
            # AR021: record the verifier-confirmed outcome (the only legal
            # success signal) so the registry learns which skills work.
            record_skill_outcome(
                skill.name,
                subtask.operation,
                ok,
                "" if ok else result.error,
            )

        if not ok and fallback:
            rollout = await rollout_task(
                env,
                subtask,
                model,
                tokenizer,
                repair=False,
                sample=False,
                max_steps=max_steps_per_subtask,
                reward_mode="vgdp",
                initial_obs=obs,
                semantic=semantic,
            )
            steps.extend(rollout.steps)
            obs = await env.observe()
            ok = rollout.success

        if not ok:
            break

    final = compute_progress(obs["state"], obs["url"], task)
    return Rollout(
        task_id=task.task_id,
        success=final.success,
        final_progress=final.progress,
        steps=steps,
        raw_invalid=sum(1 for step in steps if step.raw_invalid),
        repaired=sum(1 for step in steps if step.repaired),
        total_steps=len(steps),
    )
