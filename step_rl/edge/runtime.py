"""Unified Agent Runtime: plan -> compiled skills -> replan -> LLM fallback."""

from __future__ import annotations

from typing import Any, Dict, List

from .browser import BrowserEnv
from .hierarchical import run_hierarchy
from .planner import fetch_catalog, plan_instruction
from .skill_library import run_skill_hierarchy


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
