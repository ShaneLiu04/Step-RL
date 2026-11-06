"""Closed-loop runtime supervision: plan, act, verify, refresh, replan."""

from __future__ import annotations

from typing import Any, Dict, List

from .browser import BrowserEnv
from .hierarchical import run_hierarchy
from .planner import fetch_catalog, plan_instruction


async def run_supervised(
    env: BrowserEnv,
    instruction: str,
    model,
    tokenizer,
    *,
    max_attempts: int = 2,
    max_steps_per_subtask: int = 12,
    semantic: bool = True,
    planner=plan_instruction,
) -> Dict[str, Any]:
    """Run a task; on failure refresh the real catalog and replan once."""

    catalog = fetch_catalog(env.server.base_url)
    spec = planner(instruction, catalog)
    attempts: List[Dict[str, Any]] = []
    if spec is None:
        return {
            "instruction": instruction,
            "success": False,
            "spec": None,
            "attempts": attempts,
            "replanned": False,
        }

    success = False
    for attempt in range(1, max_attempts + 1):
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
                "attempt": attempt,
                "targets": dict(spec.targets),
                "success": rollout.success,
                "steps": rollout.total_steps,
                "final_progress": rollout.final_progress,
            }
        )
        if rollout.success:
            success = True
            break
        if attempt >= max_attempts:
            break

        # Re-read the real catalog after the environment drift, then replan.
        refreshed = fetch_catalog(env.server.base_url)
        new_spec = planner(instruction, refreshed)
        if new_spec is None or new_spec.targets == spec.targets:
            break
        spec = new_spec

    return {
        "instruction": instruction,
        "success": success,
        "spec": None if spec is None else dict(spec.targets),
        "attempts": attempts,
        "replanned": len(attempts) > 1,
    }
