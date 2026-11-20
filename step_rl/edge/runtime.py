"""Unified Agent Runtime: plan -> compiled skills -> replan -> LLM fallback."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, List, Tuple

from .browser import BrowserEnv
from .hierarchical import run_hierarchy
from .planner import fetch_catalog, fetch_promos, plan_instruction
from .rollout import StepRecord
from .skill_library import run_skill, run_skill_hierarchy, update_quantity_skill
from .tasks import TaskSpec
from .verifier import compute_progress


def _transform_targets(
    cart: Dict[str, int], expression: str
) -> Tuple[Dict[str, int], str]:
    current = {pid: int(qty) for pid, qty in cart.items()}
    if not current:
        return {}, "cart is empty"
    if expression == "double":
        targets = {pid: qty * 2 for pid, qty in current.items()}
    elif expression.startswith("set:"):
        try:
            value = int(expression.split(":", 1)[1])
        except ValueError:
            return {}, f"invalid transform: {expression}"
        targets = {pid: value for pid in current}
    elif expression.startswith("add:"):
        try:
            value = int(expression.split(":", 1)[1])
        except ValueError:
            return {}, f"invalid transform: {expression}"
        targets = {pid: qty + value for pid, qty in current.items()}
    else:
        return {}, f"unsupported transform: {expression}"
    if any(qty < 1 or qty > 9 for qty in targets.values()):
        return {}, f"transform exceeds site quantity range: {targets}"
    return targets, ""


async def run_cart_transform(env: BrowserEnv, spec: TaskSpec) -> Dict[str, Any]:
    """AR027: execute a cart-wide update as a real compensating transaction."""

    before = await env.get_state()
    original = {pid: int(qty) for pid, qty in (before.get("cart") or {}).items()}
    targets = dict(spec.targets)
    obs = await env.observe()
    changed: List[Tuple[str, int]] = []
    actions: List[Dict[str, Any]] = []
    for pid, target in sorted(targets.items()):
        if original.get(pid, 0) == target:
            continue
        result = await run_skill(
            env,
            update_quantity_skill(pid, target, adaptive=True),
            initial_obs=obs,
        )
        actions.extend(result.actions)
        obs = result.observation or await env.observe()
        current_state = await env.get_state()
        verified = (
            result.success
            and int((current_state.get("cart") or {}).get(pid, 0)) == target
        )
        if not verified:
            error = result.error or (
                f"verifier-confirmed mismatch: {pid} target={target}"
            )
            compensated = 0
            for done_pid, original_qty in changed:
                compensation = await run_skill(
                    env,
                    update_quantity_skill(done_pid, original_qty, adaptive=True),
                    initial_obs=obs,
                )
                obs = compensation.observation or await env.observe()
                restored = await env.get_state()
                compensated += int(
                    compensation.success
                    and int((restored.get("cart") or {}).get(done_pid, 0))
                    == original_qty
                )
            return {
                "success": False,
                "spec": targets,
                "attempts": [
                    {
                        "attempt": 1,
                        "mode": "cart_transform",
                        "transform": spec.cart_transform,
                        "success": False,
                        "steps": len(actions),
                        "error": error,
                        "compensated": compensated,
                    }
                ],
                "steps": _skill_records(actions),
                "fallback": False,
                "transform": spec.cart_transform,
                "error": error,
                "compensated": compensated,
            }
        changed.append((pid, original.get(pid, 0)))

    state = await env.get_state()
    progress = compute_progress(state, env.page_url_path, spec)
    return {
        "success": progress.success,
        "spec": targets,
        "attempts": [
            {
                "attempt": 1,
                "mode": "cart_transform",
                "transform": spec.cart_transform,
                "success": progress.success,
                "steps": len(actions),
                "compensated": 0,
            }
        ],
        "steps": _skill_records(actions),
        "fallback": False,
        "transform": spec.cart_transform,
    }


def _skill_records(actions: List[Dict[str, Any]]) -> List[StepRecord]:
    return [
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
        for action in actions
    ]


async def run_task(
    env: BrowserEnv,
    instruction: str,
    model,
    tokenizer,
    *,
    max_attempts: int = 2,
    semantic: bool = True,
    max_steps_per_subtask: int = 12,
    skill_retries: int = 0,
    enable_cart_transform: bool = True,
) -> Dict[str, Any]:
    """Execute one natural-language task with the full composed runtime."""

    catalog = fetch_catalog(env.server.base_url)
    promos = fetch_promos(env.server.base_url)
    spec = plan_instruction(
        instruction,
        catalog,
        promos,
        enable_cart_transform=enable_cart_transform,
    )
    attempts: List[Dict[str, Any]] = []
    if spec is None:
        return {
            "success": False,
            "spec": None,
            "attempts": attempts,
            "steps": [],
            "fallback": False,
            "fallback_required": True,
        }

    if spec.cart_transform:
        current = await env.get_state()
        targets, error = _transform_targets(
            current.get("cart") or {}, spec.cart_transform
        )
        if error:
            return {
                "success": False,
                "spec": {},
                "attempts": [],
                "steps": [],
                "fallback": False,
                "error": error,
                "transform": spec.cart_transform,
            }
        spec = replace(spec, targets=targets, predicates=["cart_contains"])
        return await run_cart_transform(env, spec)

    retries_used = 0
    for attempt in range(1, max_attempts + 1):
        rollout = await run_skill_hierarchy(
            env,
            spec,
            model,
            tokenizer,
            fallback=False,
            semantic=semantic,
            max_steps_per_subtask=max_steps_per_subtask,
        )
        attempts.append(
            {
                "attempt": attempt,
                "targets": dict(spec.targets),
                "success": rollout.success,
                "steps": rollout.total_steps,
                "final_progress": rollout.final_progress,
            }
        )
        if rollout.success:
            return {
                "success": True,
                "spec": dict(spec.targets),
                "attempts": attempts,
                "steps": rollout.steps,
                "fallback": False,
            }

        if retries_used < skill_retries and attempt < max_attempts:
            retries_used += 1
            attempts[-1]["mode"] = "retry"
            continue

        refreshed = fetch_catalog(env.server.base_url)
        new_spec = plan_instruction(
            instruction,
            refreshed,
            promos,
            enable_cart_transform=enable_cart_transform,
        )
        if new_spec is None or new_spec.targets == spec.targets:
            break
        spec = new_spec

    if model is None:
        return {
            "success": False,
            "spec": dict(spec.targets),
            "attempts": attempts,
            "steps": [],
            "fallback": True,
            "fallback_required": True,
        }

    # Skill execution could not satisfy the task (or the plan stayed the same):
    # hand the current state to the LLM hierarchy.
    rollout = await run_hierarchy(
        env,
        spec,
        model,
        tokenizer,
        repair=False,
        max_steps_per_subtask=max_steps_per_subtask,
        semantic=semantic,
    )
    attempts.append(
        {
            "attempt": len(attempts) + 1,
            "targets": dict(spec.targets),
            "success": rollout.success,
            "steps": rollout.total_steps,
            "final_progress": rollout.final_progress,
            "mode": "llm_fallback",
        }
    )
    return {
        "success": rollout.success,
        "spec": dict(spec.targets),
        "attempts": attempts,
        "steps": rollout.steps,
        "fallback": True,
    }


async def run_order_sequence(
    env: BrowserEnv,
    task: TaskSpec,
    model,
    tokenizer,
    *,
    semantic: bool = True,
    max_steps_per_subtask: int = 12,
    compensate: bool = False,
) -> Dict[str, Any]:
    """Execute an ordered list of independent orders."""

    compensate = compensate or task.compensate_on_failure
    attempts = []
    placed: List[str] = []
    for index, targets in enumerate(task.order_sequence):
        subtask = TaskSpec(
            task_id=f"{task.task_id}_order_{index}",
            level=5 if len(targets) > 1 else 4,
            goal=f"完成第 {index + 1} 笔订单",
            search_query=next(iter(targets)),
            targets=dict(targets),
            require_checkout=True,
        )
        before = await env.get_state()
        before_ids = {order["id"] for order in before.get("orders", [])}
        rollout = await run_skill_hierarchy(
            env,
            subtask,
            model,
            tokenizer,
            fallback=False,
            semantic=semantic,
            max_steps_per_subtask=max_steps_per_subtask,
            reset=(index == 0),
        )
        attempts.append(
            {
                "order": index + 1,
                "targets": dict(targets),
                "success": rollout.success,
                "steps": rollout.total_steps,
            }
        )
        if rollout.success:
            after = await env.get_state()
            placed.extend(
                order["id"]
                for order in after.get("orders", [])
                if order["id"] not in before_ids
            )
            continue

        if compensate:
            for order_id in placed:
                await env.cancel_order(order_id)
        break
    state = await env.get_state()
    progress = compute_progress(state, env.page_url_path, task)
    return {
        "success": progress.success,
        "orders": state.get("orders", []),
        "attempts": attempts,
        "steps": [],
    }
