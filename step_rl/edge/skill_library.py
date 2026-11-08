"""Parameterised skills compiled from successful expert action patterns.

Skills execute against the real DOM through semantic names; they do not call
the language model.  A failed skill falls back to the regular LLM hierarchy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .browser import BrowserEnv
from .hierarchical import adapter_for_subtask, decompose_task
from .rollout import Rollout, StepRecord, rollout_task
from .site import PRODUCTS
from .tasks import TaskSpec
from .verifier import compute_progress

NAME_VALUE = "刘星言先生"
ADDRESS_VALUE = "深圳市龙岗区坂田路1号"


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
) -> Rollout:
    obs = await env.reset(task)
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
