"""Real rollouts: browser interaction + policy generation + verifier reward."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import torch

from .browser import BrowserEnv
from .expert import expert_action
from .policy import build_prompt, parse_action, render_action, repair_action
from .skill_memory import SkillMemory
from .tasks import TaskSpec
from .verifier import compute_progress


@dataclass
class StepRecord:
    prompt: str
    prompt_ids: List[int]
    response_ids: List[int]
    old_logprobs: List[float]
    response_text: str
    action: Dict[str, Any]
    exec_ok: bool
    error: str
    phi_before: float
    phi_after: float
    reward: float = 0.0
    advantage: float = 0.0
    raw_invalid: bool = False
    repaired: bool = False
    source: str = "policy"


@dataclass
class Rollout:
    task_id: str
    success: bool
    final_progress: float
    steps: List[StepRecord] = field(default_factory=list)
    raw_invalid: int = 0
    repaired: int = 0
    total_steps: int = 0


def _model_device(model) -> torch.device:
    return next(model.parameters()).device


def generate_action(
    model,
    tokenizer,
    prompt: str,
    sample: bool = True,
    max_new_tokens: int = 96,
    temperature: float = 1.0,
    max_prompt_tokens: int = 1024,
) -> Dict[str, Any]:
    device = _model_device(model)
    encoded = tokenizer(
        prompt,
        return_tensors="pt",
        add_special_tokens=False,
        truncation=True,
        max_length=max_prompt_tokens,
    )
    input_ids = encoded.input_ids.to(device)
    attention = encoded.attention_mask.to(device)
    gen_kwargs = dict(
        max_new_tokens=max_new_tokens,
        do_sample=sample,
        output_scores=True,
        return_dict_in_generate=True,
        pad_token_id=tokenizer.pad_token_id,
        eos_token_id=tokenizer.eos_token_id,
    )
    if sample:
        gen_kwargs.update(temperature=temperature, top_p=1.0)
    with torch.no_grad():
        out = model.generate(
            input_ids=input_ids, attention_mask=attention, **gen_kwargs
        )
    prompt_len = input_ids.shape[1]
    response_ids = out.sequences[0, prompt_len:].tolist()
    old_logprobs: List[float] = []
    if out.scores is not None:
        for score, token_id in zip(out.scores, response_ids):
            logp = torch.log_softmax(score[0].float(), dim=-1)[token_id]
            old_logprobs.append(float(logp))
    # Trim to the generated length (defensive for older transformers).
    if len(old_logprobs) < len(response_ids):
        old_logprobs.extend([0.0] * (len(response_ids) - len(old_logprobs)))
    old_logprobs = old_logprobs[: len(response_ids)]
    text = tokenizer.decode(response_ids, skip_special_tokens=True)
    return {
        "text": text,
        "prompt_ids": input_ids[0].tolist(),
        "response_ids": response_ids,
        "old_logprobs": old_logprobs,
    }


def step_reward(
    phi_before: float,
    phi_after: float,
    exec_ok: bool,
    terminal: bool,
    success: bool,
    mode: str = "vgdp",
    loop: bool = False,
) -> float:
    if mode == "sparse":
        reward = -0.02
        if terminal:
            reward += 1.0 if success else 0.0
        return reward
    reward = 2.0 * (phi_after - phi_before)
    reward += 0.05 if exec_ok else -0.10
    reward -= 0.02
    if loop:
        reward -= 0.10
    if terminal:
        reward += 1.0 if success else -0.10
    return reward


async def rollout_task(
    env: BrowserEnv,
    task: TaskSpec,
    model,
    tokenizer,
    *,
    repair: bool = True,
    sample: bool = True,
    max_steps: int = 12,
    max_new_tokens: int = 96,
    reward_mode: str = "vgdp",
    prime_steps: int = 0,
    memory: Optional[SkillMemory] = None,
    memory_prompt: bool = False,
    replan: bool = False,
    initial_obs: Optional[Dict[str, Any]] = None,
) -> Rollout:
    obs = initial_obs if initial_obs is not None else await env.reset(task)
    progress = compute_progress(obs["state"], obs["url"], task)
    phi = progress.progress
    missing = list(progress.missing)
    history: List[str] = []
    steps: List[StepRecord] = []
    raw_invalid = 0
    repaired_count = 0
    success = False
    recent_actions: List[str] = []
    stagnation = 0
    replan_budget = 3

    # Curriculum priming with the real expert, executed in the real browser.
    # This is used identically for sparse and dense RL so the only difference
    # between the two runs is the reward signal.
    for _ in range(max(0, prime_steps)):
        teacher = expert_action(task, obs)
        result = await env.execute(teacher)
        obs = await env.observe()
        progress = compute_progress(obs["state"], obs["url"], task)
        phi = progress.progress
        missing = list(progress.missing)
        history.append(
            f"teacher:{teacher.get('action')} -> "
            f"{'ok' if result['ok'] else 'fail'} phi={phi:.2f}"
        )
        if result.get("terminal") or phi >= 1.0:
            return Rollout(
                task_id=task.task_id,
                success=phi >= 1.0,
                final_progress=phi,
                steps=[],
                total_steps=0,
            )

    for _ in range(max_steps):
        suggestion = None
        reference = None
        if memory is not None and task.require_checkout:
            suggestion = memory.retrieve(task, obs["url"], missing, obs["state"])
            if suggestion is not None:
                reference = memory.resolve(suggestion, task, obs["state"])

        # Verifier-triggered replanning: when progress has been stagnant for
        # two consecutive model steps, execute one memory action for real.
        if replan and stagnation >= 2 and replan_budget > 0 and reference is not None:
            replan_budget -= 1
            exec_result = await env.execute(reference)
            obs_after = await env.observe()
            progress_after = compute_progress(
                obs_after["state"], obs_after["url"], task
            )
            phi_after = progress_after.progress
            reward = step_reward(
                phi,
                phi_after,
                bool(exec_result["ok"]),
                bool(exec_result.get("terminal")),
                phi_after >= 1.0,
                mode=reward_mode,
            )
            steps.append(
                StepRecord(
                    prompt="memory_replan",
                    prompt_ids=[],
                    response_ids=[],
                    old_logprobs=[],
                    response_text=render_action(reference),
                    action=reference,
                    exec_ok=bool(exec_result["ok"]),
                    error=str(exec_result.get("error", "")),
                    phi_before=phi,
                    phi_after=phi_after,
                    reward=reward,
                    source="memory_replan",
                )
            )
            history.append(
                f"replan:{reference.get('action')} -> "
                f"{'ok' if exec_result['ok'] else 'fail'} phi={phi_after:.2f}"
            )
            phi = phi_after
            missing = list(progress_after.missing)
            success = phi >= 1.0
            stagnation = 0
            if exec_result.get("terminal") or success:
                break
            obs = obs_after
            continue

        prompt = build_prompt(
            task.goal,
            obs,
            history,
            progress=phi,
            missing=missing,
            reference_action=reference if memory_prompt else None,
        )
        gen = generate_action(
            model, tokenizer, prompt, sample=sample, max_new_tokens=max_new_tokens
        )
        action = parse_action(gen["text"])
        repaired_info = {"raw_invalid": False, "repaired": False, "reason": ""}
        if repair:
            action, repaired_info = repair_action(action, obs.get("elements", []))
        raw_invalid += int(repaired_info["raw_invalid"])
        repaired_count += int(repaired_info["repaired"])

        exec_result = await env.execute(action)
        obs_after = await env.observe()
        progress_after = compute_progress(obs_after["state"], obs_after["url"], task)
        phi_after = progress_after.progress
        key = f"{action.get('action')}:{action.get('params')}"
        loop = key in recent_actions[-2:]
        recent_actions.append(key)
        reward = step_reward(
            phi,
            phi_after,
            bool(exec_result["ok"]),
            bool(exec_result.get("terminal")),
            phi_after >= 1.0,
            mode=reward_mode,
            loop=loop,
        )
        steps.append(
            StepRecord(
                prompt=prompt,
                prompt_ids=gen["prompt_ids"],
                response_ids=gen["response_ids"],
                old_logprobs=gen["old_logprobs"],
                response_text=gen["text"],
                action=action,
                exec_ok=bool(exec_result["ok"]),
                error=str(exec_result.get("error", "")),
                phi_before=phi,
                phi_after=phi_after,
                reward=reward,
                raw_invalid=bool(repaired_info["raw_invalid"]),
                repaired=bool(repaired_info["repaired"]),
                source="policy",
            )
        )
        history.append(
            f"{_short(gen['text'])} -> {'ok' if exec_result['ok'] else 'fail'} "
            f"phi={phi_after:.2f}"
        )
        phi = phi_after
        missing = list(progress_after.missing)
        success = phi >= 1.0
        if phi_after <= steps[-1].phi_before or not exec_result["ok"]:
            stagnation += 1
        else:
            stagnation = 0
        if exec_result.get("terminal") or success:
            break
        obs = obs_after

    return Rollout(
        task_id=task.task_id,
        success=success,
        final_progress=phi,
        steps=steps,
        raw_invalid=raw_invalid,
        repaired=repaired_count,
        total_steps=len(steps),
    )


def _short(text: str, limit: int = 90) -> str:
    text = " ".join(text.split())
    return text[:limit]


def returns_to_go(rewards: List[float], gamma: float = 0.95) -> List[float]:
    out = []
    running = 0.0
    for reward in reversed(rewards):
        running = reward + gamma * running
        out.append(running)
    return list(reversed(out))


def assign_group_advantages(rollouts: List[Rollout], gamma: float = 0.95) -> None:
    """Normalize step returns within each task group (GRPO)."""

    groups: Dict[str, List[Rollout]] = {}
    for rollout in rollouts:
        groups.setdefault(rollout.task_id, []).append(rollout)
    for group in groups.values():
        values: List[float] = []
        for rollout in group:
            returns = returns_to_go([s.reward for s in rollout.steps], gamma)
            values.extend(returns)
            for step, value in zip(rollout.steps, returns):
                step.advantage = value
        if not values:
            continue
        mean = sum(values) / len(values)
        var = sum((v - mean) ** 2 for v in values) / len(values)
        std = var**0.5
        for rollout in group:
            for step in rollout.steps:
                step.advantage = (step.advantage - mean) / (std + 1e-6)


def rollout_to_dict(rollout: Rollout) -> Dict[str, Any]:
    return {
        "task_id": rollout.task_id,
        "success": rollout.success,
        "final_progress": rollout.final_progress,
        "total_steps": rollout.total_steps,
        "raw_invalid": rollout.raw_invalid,
        "repaired": rollout.repaired,
        "steps": [
            {
                "action": s.action,
                "exec_ok": s.exec_ok,
                "error": s.error,
                "phi_before": s.phi_before,
                "phi_after": s.phi_after,
                "reward": s.reward,
                "advantage": s.advantage,
                "raw_invalid": s.raw_invalid,
                "repaired": s.repaired,
                "source": s.source,
            }
            for s in rollout.steps
        ],
    }
