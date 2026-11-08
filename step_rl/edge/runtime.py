"""Unified Agent Runtime: plan -> compiled skills -> replan -> LLM fallback."""

from __future__ import annotations

from typing import Any, Dict, List

from .browser import BrowserEnv
from .hierarchical import run_hierarchy
from .planner import fetch_catalog, plan_instruction
from .skill_library import run_skill_hierarchy
from .tasks import TaskSpec
from .verifier import compute_progress


async def run_task(
    env: BrowserEnv,
    instruction: str,
    model,
    tokenizer,
    *,
    max_attempts: int = 2,
    semantic: bool = True,
    max_steps_per_subtask: int = 12,
) -> Dict[str, Any]:
    """Execute one natural-language task with the full composed runtime."""

    catalog = fetch_catalog(env.server.base_url)
    spec = plan_instruction(instruction, catalog)
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

        refreshed = fetch_catalog(env.server.base_url)
        new_spec = plan_instruction(instruction, refreshed)
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
) -> Dict[str, Any]:
    """Execute an ordered list of independent orders."""

    attempts = []
    for index, targets in enumerate(task.order_sequence):
        subtask = TaskSpec(
            task_id=f"{task.task_id}_order_{index}",
            level=5 if len(targets) > 1 else 4,
            goal=f"完成第 {index + 1} 笔订单",
            search_query=next(iter(targets)),
            targets=dict(targets),
            require_checkout=True,
        )
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
        if not rollout.success:
            break
    state = await env.get_state()
    progress = compute_progress(state, env.page_url_path, task)
    return {
        "success": progress.success,
        "orders": state.get("orders", []),
        "attempts": attempts,
        "steps": [],
    }
