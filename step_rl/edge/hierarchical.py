"""Verifier-Guided Hierarchical Task Decomposition (AR003).

Long-horizon tasks are split into ordered subgoals using the verifier's
predicate chain.  Each subgoal is handled by the adapter specialised for that
skill, while the browser session persists so cart state is never reset.
"""

from __future__ import annotations

from typing import List

from .browser import BrowserEnv
from .rollout import Rollout, StepRecord, rollout_task
from .site import PRODUCTS
from .tasks import TaskSpec
from .verifier import compute_progress


def decompose_task(task: TaskSpec) -> List[TaskSpec]:
    """Split a checkout task into add-item subgoals + checkout."""

    if not task.require_checkout:
        return [task]

    subtasks: List[TaskSpec] = []
    for pid, qty in task.targets.items():
        product_types = {pid: qty}
        level = 3 if qty >= 2 else 2
        product = PRODUCTS.get(pid)
        query = product.keywords[0] if product else task.search_query
        name = product.name if product else pid
        subtasks.append(
            TaskSpec(
                task_id=f"{task.task_id}__add_{pid}",
                level=level,
                goal=f"搜索“{query}”，将商品 {name} 数量 {qty} 加入购物车。",
                search_query=query,
                targets=product_types,
                require_checkout=False,
                split="subtask",
            )
        )
    subtasks.append(
        TaskSpec(
            task_id=f"{task.task_id}__checkout",
            level=4,
            goal="完成结算并提交订单。",
            search_query=task.search_query,
            targets=dict(task.targets),
            require_checkout=True,
            split="subtask",
        )
    )
    return subtasks


def adapter_for_subtask(subtask: TaskSpec) -> str:
    if subtask.require_checkout:
        return "checkout"
    if any(qty >= 2 for qty in subtask.targets.values()):
        return "quantity"
    return "base"


async def run_hierarchy(
    env: BrowserEnv,
    task: TaskSpec,
    model,
    tokenizer,
    *,
    repair: bool = True,
    max_steps_per_subtask: int = 8,
    sample: bool = False,
    semantic: bool = False,
) -> Rollout:
    obs = await env.reset(task)
    all_steps: List[StepRecord] = []
    subtasks = decompose_task(task)
    subtask_success = True

    for index, subtask in enumerate(subtasks):
        adapter = adapter_for_subtask(subtask)
        if hasattr(model, "set_adapter"):
            model.set_adapter(adapter)

        if index > 0:
            target = "/checkout" if subtask.require_checkout else "/"
            action = {"action": "goto", "params": {"url": target}}
            result = await env.execute(action)
            all_steps.append(
                StepRecord(
                    prompt="controller_navigation",
                    prompt_ids=[],
                    response_ids=[],
                    old_logprobs=[],
                    response_text=target,
                    action=action,
                    exec_ok=bool(result["ok"]),
                    error=str(result.get("error", "")),
                    phi_before=0.0,
                    phi_after=0.0,
                    source="controller",
                )
            )
            obs = await env.observe()

        rollout = await rollout_task(
            env,
            subtask,
            model,
            tokenizer,
            repair=repair,
            sample=sample,
            max_steps=max_steps_per_subtask,
            reward_mode="vgdp",
            initial_obs=obs,
            semantic=semantic,
        )
        all_steps.extend(rollout.steps)
        obs = await env.observe()
        if not rollout.success:
            subtask_success = False
            break

    final = compute_progress(obs["state"], obs["url"], task)
    return Rollout(
        task_id=task.task_id,
        success=final.success and subtask_success,
        final_progress=final.progress,
        steps=all_steps,
        raw_invalid=sum(1 for step in all_steps if step.raw_invalid),
        repaired=sum(1 for step in all_steps if step.repaired),
        total_steps=len(all_steps),
    )
