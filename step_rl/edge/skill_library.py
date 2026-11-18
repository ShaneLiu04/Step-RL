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

AR024 makes the registry safe for concurrent sessions: the
check-then-append upsert in :func:`register_induced_skill` runs in a
single critical section (no duplicate candidates under parallel
registration), and persistence takes a consistent snapshot under the
lock and atomically replaces the file (no interleaved writes).  Serial
semantics, JSON shapes and the selection rule are unchanged.
"""

from __future__ import annotations

import itertools
import json
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from .browser import BrowserEnv
from .concurrency import atomic_write_json
from .hierarchical import adapter_for_subtask, decompose_task
from .rollout import Rollout, StepRecord, rollout_task
from .site import PRODUCTS, PROMOS
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

# AR026: semantic control aliases.  A step names the *capability*, not a
# layout-specific role/label; the live observation decides which control exists.
ROLE_ALIASES = {
    "textbox": ("textbox", "searchbox"),
    "spinbutton": ("spinbutton",),
}
NAME_ALIASES = {
    "搜索": ("搜索", "查找"),
    "搜索商品": ("搜索商品", "输入关键词"),
}


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


# operation -> [candidate {"name", "steps", "order", "registered_at"}]
# AR021: multiple candidates may coexist per operation; selection by real
# success rate (see skill_stats), demoted candidates yield.
_INDUCED: Dict[str, List[Dict[str, Any]]] = {}
_ORDER = itertools.count(1)

# AR024: guards the registry's check-then-act paths (upsert, clear and
# the persist snapshot).  Lock order with skill_stats is always
# registry -> stats (never the reverse), so no deadlock.
_LOCK = threading.Lock()


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

    AR024: the name lookup and the replace/append are one critical
    section - parallel registrations of the same name can no longer both
    pass the check and both append (probe E3 produced duplicate
    candidates on the old code).
    """

    candidate_name = name or f"induced_{operation}"
    with _LOCK:
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
    with _LOCK:
        _INDUCED.clear()


def induced_operations() -> List[str]:
    return sorted(_INDUCED)


def save_induced_skills(path: str) -> None:
    """Persist the selected candidate of each operation.

    File shape stays the AR019/AR020 one (``{"op": {"name", "steps"}}``):
    with a single candidate it is field-for-field identical to the old
    output.  Operations whose candidates are all demoted are omitted -
    the file honestly states that no usable skill exists for them.

    AR024: the snapshot (including the ``_select_best`` reads) is taken
    inside one critical section, then the file is atomically replaced -
    a saved file is always one consistent registry state, even when
    several sessions persist at the same time.
    """

    with _LOCK:
        data: Dict[str, Any] = {}
        for operation in _INDUCED:
            best = _select_best(operation)
            if best is None:
                continue
            data[operation] = {
                "name": best["name"],
                "steps": [dict(step) for step in best["steps"]],
            }
    atomic_write_json(path, data)


def load_induced_skills(path: str) -> List[str]:
    """Load and register persisted induced-skill templates."""

    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    for operation, entry in data.items():
        register_induced_skill(operation, entry.get("steps", []), entry.get("name", ""))
    return sorted(data)


def _placeholder_product(step: Dict[str, Any]) -> bool:
    return "{product}" in str(step.get("name", "")) or "{product}" in str(
        step.get("value", "")
    )


def _split_product_unit(steps: List[Dict[str, Any]]):
    """Split template steps into ``(prefix, unit, suffix)``.

    The *unit* is the maximal run of ``{product}`` steps starting at the
    first such step; everything before it (page setup such as
    ``goto /cart``) belongs to the prefix and runs once, everything after
    the suffix (runs once).  Templates without any ``{product}`` step
    degenerate to ``(steps, [], [])``.
    """

    first = next(
        (i for i, item in enumerate(steps) if _placeholder_product(item)), None
    )
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
    observation: Optional[Dict[str, Any]] = None


def search_skill(query: str) -> Skill:
    return Skill(
        "search",
        [
            SkillStep("goto", url="/"),
            SkillStep("type", name="搜索商品", role="textbox", value=query),
            SkillStep("click", name="搜索", role="button"),
        ],
    )


def add_item_skill(pid: str, qty: int, adaptive: bool = True) -> Skill:
    product = PRODUCTS[pid]
    query = product.keywords[0] if product.keywords else product.name
    quantity_step = (
        SkillStep("set_quantity", name="数量", role="spinbutton", value=str(qty))
        if adaptive
        else SkillStep("type", name="数量", role="spinbutton", value=str(qty))
    )
    return Skill(
        "add_item",
        [
            SkillStep("goto", url="/"),
            SkillStep("type", name="搜索商品", role="textbox", value=query),
            SkillStep("click", name="搜索", role="button"),
            SkillStep("click", name=product.name, role="link"),
            quantity_step,
            SkillStep("click", name="加入购物车", role="button"),
        ],
    )


def update_quantity_skill(pid: str, qty: int, adaptive: bool = True) -> Skill:
    product = PRODUCTS[pid]
    quantity_step = (
        SkillStep("set_quantity", name=product.name, role="spinbutton", value=str(qty))
        if adaptive
        else SkillStep("type", name=product.name, role="spinbutton", value=str(qty))
    )
    return Skill(
        "update_quantity",
        [
            SkillStep("goto", url="/cart"),
            quantity_step,
            SkillStep(
                "click",
                name=f"更新数量 {product.name}",
                role="button",
            ),
        ],
    )


def checkout_skill(promo_code: str = "") -> Skill:
    """Compiled checkout flow.

    AR023: a valid ``promo_code`` inserts one real claim step
    (``click button 「领取{label}优惠」``) right before 提交订单; with no
    code the emitted steps are field-for-field the historical four.
    """

    steps = [
        SkillStep("goto", url="/checkout"),
        SkillStep("type", name="收货人", role="textbox", value=NAME_VALUE),
        SkillStep("type", name="地址", role="textbox", value=ADDRESS_VALUE),
    ]
    if promo_code and promo_code in PROMOS:
        steps.append(
            SkillStep(
                "click",
                name=f"领取{PROMOS[promo_code].label}优惠",
                role="button",
            )
        )
    steps.append(SkillStep("click", name="提交订单", role="button"))
    return Skill("checkout", steps)


def skill_for_subtask(task: TaskSpec, adaptive: bool = True) -> Optional[Skill]:
    if task.operation == "update":
        pid = next(iter(task.targets), None)
        if pid:
            return update_quantity_skill(pid, task.targets[pid], adaptive=adaptive)
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
        return checkout_skill(task.promo)
    pid = next(iter(task.targets), None)
    if pid:
        return add_item_skill(pid, task.targets[pid], adaptive=adaptive)
    return None


def _find(elements: List[Dict[str, Any]], step: SkillStep) -> Optional[Dict[str, Any]]:
    candidates = []
    roles = ROLE_ALIASES.get(step.role or "", (step.role,)) if step.role else (None,)
    names = NAME_ALIASES.get(step.name, (step.name,)) if step.name else ("",)
    for element in elements:
        if step.role and element.get("role") not in roles:
            continue
        name = element.get("accessible_name", "")
        if step.name and not any(alias.lower() in name.lower() for alias in names):
            continue
        if any(word in name for word in ("推荐", "广告", "赞助")):
            continue
        candidates.append(element)
    if not candidates:
        return None
    for element in candidates:
        accessible = element.get("accessible_name", "").strip().lower()
        if any(accessible == alias.lower() for alias in names):
            return element
    return candidates[0]


def _int_value(raw: Any) -> Optional[int]:
    text = str(raw or "").strip()
    try:
        return int(text)
    except ValueError:
        digits = "".join(ch for ch in text if ch.isdigit())
        return int(digits) if digits else None


def _find_control(
    elements: List[Dict[str, Any]], verb: str, needle: str
) -> Optional[Dict[str, Any]]:
    for element in elements:
        if element.get("role") != "button":
            continue
        name = str(element.get("accessible_name", ""))
        if verb in name and needle in name:
            return element
    return None


async def _apply_quantity(
    env: BrowserEnv,
    obs: Dict[str, Any],
    step: SkillStep,
) -> tuple[List[Dict[str, Any]], Dict[str, Any], str]:
    """Compile a quantity target against the live control inventory.

    v1/v2 expose an <input type=number>: fill it.  v3 exposes a stepper
    (spinbutton display + 增加/减少 buttons): click the real delta.
    """

    element = _find(
        obs.get("elements", []), SkillStep("type", name=step.name, role="spinbutton")
    )
    if element is None:
        element = next(
            (
                candidate
                for candidate in obs.get("elements", [])
                if candidate.get("role") == "spinbutton"
            ),
            None,
        )
    if element is None:
        return [], obs, f"quantity control not found: {step.name}"
    target = _int_value(step.value)
    if target is None:
        return [], obs, f"invalid quantity target: {step.value}"
    if element.get("tag") == "input":
        action = {
            "action": "type",
            "params": {"element": element["eid"], "text": str(target)},
        }
        result = await env.execute(action)
        if not result.get("ok"):
            return [action], obs, str(result.get("error", ""))
        return [action], await env.observe(), ""

    current = _int_value(element.get("value")) or 1
    delta = target - current
    actions: List[Dict[str, Any]] = []
    while delta != 0:
        verb = "增加" if delta > 0 else "减少"
        button = _find_control(obs.get("elements", []), verb, step.name)
        if button is None:
            return actions, obs, f"stepper control not found: {verb}{step.name}"
        action = {"action": "click", "params": {"element": button["eid"]}}
        result = await env.execute(action)
        actions.append(action)
        if not result.get("ok"):
            return actions, obs, str(result.get("error", ""))
        obs = await env.observe()
        delta = -1 if delta < 0 else delta - 1
    return actions, obs, ""


async def run_skill(
    env: BrowserEnv,
    skill: Skill,
    initial_obs: Optional[Dict[str, Any]] = None,
) -> SkillResult:
    obs = initial_obs if initial_obs is not None else await env.observe()
    actions: List[Dict[str, Any]] = []
    for step in skill.steps:
        if step.kind == "set_quantity":
            step_actions, obs, error = await _apply_quantity(env, obs, step)
            actions.extend(step_actions)
            if error:
                return SkillResult(False, actions, error, obs)
            continue
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
                return SkillResult(
                    False, actions, f"element not found: {step.name}", obs
                )
            params = {"element": element["eid"]}
            if step.kind == "type":
                params["text"] = step.value
            action = {"action": step.kind, "params": params}
        result = await env.execute(action)
        actions.append(action)
        if not result.get("ok"):
            return SkillResult(False, actions, str(result.get("error", "")), obs)
        obs = await env.observe()
    return SkillResult(True, actions, "", obs)


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
    adaptive: bool = True,
) -> Rollout:
    obs = await env.reset(task) if reset else await env.observe()
    steps: List[StepRecord] = []
    for subtask in decompose_task(task):
        adapter = adapter_for_subtask(subtask)
        if hasattr(model, "set_adapter"):
            model.set_adapter(adapter)
        skill = skill_for_subtask(subtask, adaptive=adaptive)
        ok = False
        if skill is not None:
            result = await run_skill(env, skill, initial_obs=obs)
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
            obs = result.observation or await env.observe()
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
