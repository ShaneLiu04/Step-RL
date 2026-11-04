"""Step-level GRPO with verifier-grounded dense progress (VGDP).

Key differences from the legacy trainer:
* rollouts are grouped by task, not by arbitrary batches;
* old log-probs come from the exact sampling distribution (temperature=1);
* each response token inherits the advantage of its *step*;
* the reward is computed from the real executable verifier, not a model.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import torch

from .browser import BrowserEnv
from .modeling import (
    DEFAULT_MODEL,
    get_device,
    load_policy,
    resolve_model_path,
    set_seed,
)
from .rollout import Rollout, assign_group_advantages, rollout_task, rollout_to_dict
from .site import LocalShopServer
from .tasks import TRAIN_RL_TASKS, TaskSpec


def _pad_batch(steps, pad_id: int):
    max_len = max(len(s.prompt_ids) + len(s.response_ids) for s in steps)
    mask_len = max_len - 1
    input_ids, attention, old_logps, advs, masks = [], [], [], [], []
    for step in steps:
        ids = list(step.prompt_ids) + list(step.response_ids)
        pad = max_len - len(ids)
        input_ids.append(ids + [pad_id] * pad)
        attention.append([1] * len(ids) + [0] * pad)
        old = list(step.old_logprobs)
        if len(old) < len(step.response_ids):
            old += [0.0] * (len(step.response_ids) - len(old))
        old = old[: len(step.response_ids)]
        old_row = [0.0] * mask_len
        adv_row = [0.0] * mask_len
        mask = [0] * mask_len
        start = max(0, len(step.prompt_ids) - 1)
        end = min(mask_len, start + len(step.response_ids))
        for offset, idx in enumerate(range(start, end)):
            old_row[idx] = old[offset] if offset < len(old) else 0.0
            adv_row[idx] = float(step.advantage)
            mask[idx] = 1
        old_logps.append(old_row)
        advs.append(adv_row)
        masks.append(mask)
    return {
        "input_ids": torch.tensor(input_ids, dtype=torch.long),
        "attention_mask": torch.tensor(attention, dtype=torch.long),
        "old_logps": torch.tensor(old_logps, dtype=torch.float32),
        "advantages": torch.tensor(advs, dtype=torch.float32),
        "response_mask": torch.tensor(masks, dtype=torch.float32),
    }


def _token_logprobs(model, input_ids, attention_mask) -> torch.Tensor:
    logits = model(input_ids=input_ids, attention_mask=attention_mask).logits[:, :-1]
    targets = input_ids[:, 1:]
    logp = torch.log_softmax(logits.float(), dim=-1)
    return logp.gather(-1, targets.unsqueeze(-1)).squeeze(-1)


def _optimize_epoch(
    model,
    steps,
    optimizer,
    scaler,
    *,
    pad_id: int,
    device: torch.device,
    beta: float = 0.02,
    clip: float = 0.2,
    batch_size: int = 2,
    grad_accum: int = 4,
) -> Dict[str, float]:
    random.shuffle(steps)
    totals = {"loss": 0.0, "policy": 0.0, "kl": 0.0, "count": 0}
    optimizer.zero_grad(set_to_none=True)
    for index in range(0, len(steps), batch_size):
        batch = _pad_batch(steps[index : index + batch_size], pad_id)
        input_ids = batch["input_ids"].to(device)
        attention = batch["attention_mask"].to(device)
        old_logps = batch["old_logps"].to(device)
        advantages = batch["advantages"].to(device)
        mask = batch["response_mask"].to(device)
        with torch.autocast(
            device_type="cuda" if device.type == "cuda" else "cpu",
            dtype=torch.float16,
            enabled=device.type == "cuda",
        ):
            new_logps = _token_logprobs(model, input_ids, attention)
            ratio = torch.exp(new_logps - old_logps)
            unclipped = ratio * advantages
            clipped = torch.clamp(ratio, 1 - clip, 1 + clip) * advantages
            policy_loss = -(torch.minimum(unclipped, clipped) * mask).sum() / (
                mask.sum() + 1e-6
            )
        with torch.no_grad():
            with model.disable_adapter():
                ref_logps = _token_logprobs(model, input_ids, attention)
        log_ratio = ref_logps - new_logps
        kl = torch.exp(log_ratio) - log_ratio - 1.0
        kl_loss = (kl * mask).sum() / (mask.sum() + 1e-6)
        loss = policy_loss + beta * kl_loss
        scaler.scale(loss / grad_accum).backward()
        totals["loss"] += float(loss.detach())
        totals["policy"] += float(policy_loss.detach())
        totals["kl"] += float(kl_loss.detach())
        totals["count"] += 1
        if (index // batch_size + 1) % grad_accum == 0 or index + batch_size >= len(
            steps
        ):
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(
                [p for p in model.parameters() if p.requires_grad], 1.0
            )
            scaler.step(optimizer)
            scaler.update()
            optimizer.zero_grad(set_to_none=True)
    count = max(1, totals.pop("count"))
    return {key: value / count for key, value in totals.items()}


async def _collect(
    env: BrowserEnv,
    tasks: List[TaskSpec],
    model,
    tokenizer,
    group_size: int,
    reward_mode: str,
    max_steps: int,
    repair: bool,
    prime: bool = True,
    semantic: bool = False,
) -> List[Rollout]:
    rollouts: List[Rollout] = []
    # L3 must be learned from the normal entry state so the policy actually
    # learns quantity control; L4/L5 are primed to the checkout state where
    # the new skill (form filling) is exercised.
    prime_map = {3: 0, 4: 5, 5: 9}
    for task in tasks:
        for _ in range(group_size):
            rollouts.append(
                await rollout_task(
                    env,
                    task,
                    model,
                    tokenizer,
                    repair=repair,
                    sample=True,
                    max_steps=max_steps,
                    reward_mode=reward_mode,
                    prime_steps=prime_map.get(task.level, 0) if prime else 0,
                    semantic=semantic,
                )
            )
    return rollouts


async def _train_step_grpo_async(
    sft_adapter: str,
    output_dir: str,
    model_name: str = DEFAULT_MODEL,
    reward_mode: str = "vgdp",
    epochs: int = 3,
    group_size: int = 3,
    lr: float = 1e-5,
    max_steps_per_episode: int = 12,
    ppo_epochs: int = 2,
    seed: int = 42,
    tasks: Optional[List[TaskSpec]] = None,
    max_optimizer_steps: Optional[int] = None,
    semantic: bool = False,
) -> Dict[str, Any]:
    from peft import PeftModel

    set_seed(seed)
    tasks = tasks or TRAIN_RL_TASKS
    device = get_device()
    model_path = resolve_model_path(model_name)
    model, tokenizer = load_policy(model_path, sft_adapter, trainable=True)
    assert isinstance(model, PeftModel)
    optimizer = torch.optim.AdamW(
        [p for p in model.parameters() if p.requires_grad], lr=lr, weight_decay=0.0
    )
    scaler = torch.amp.GradScaler("cuda", enabled=device.type == "cuda")

    server = LocalShopServer().start()
    env = BrowserEnv(server, channel="msedge", headless=True, semantic=semantic)
    history: List[Dict[str, Any]] = []
    started = time.time()
    optimizer_steps = 0
    try:
        await env.start()
        for epoch in range(epochs):
            epoch_start = time.time()
            rollouts = await _collect(
                env,
                tasks,
                model,
                tokenizer,
                group_size,
                reward_mode,
                max_steps_per_episode,
                repair=True,
                prime=True,
                semantic=semantic,
            )
            assign_group_advantages(rollouts)
            steps = [step for rollout in rollouts for step in rollout.steps]
            stats = _optimize_epoch(
                model,
                steps,
                optimizer,
                scaler,
                pad_id=tokenizer.pad_token_id,
                device=device,
            )
            optimizer_steps += 1
            successes = sum(r.success for r in rollouts)
            mean_phi = sum(r.final_progress for r in rollouts) / max(1, len(rollouts))
            mean_reward = sum(s.reward for r in rollouts for s in r.steps) / max(
                1, len(steps)
            )
            entry = {
                "epoch": epoch + 1,
                "success_rate": successes / max(1, len(rollouts)),
                "mean_final_phi": mean_phi,
                "mean_step_reward": mean_reward,
                "steps": len(steps),
                "raw_invalid": sum(r.raw_invalid for r in rollouts),
                "repaired": sum(r.repaired for r in rollouts),
                "seconds": round(time.time() - epoch_start, 2),
                **stats,
            }
            history.append(entry)
            print(json.dumps(entry, ensure_ascii=False), flush=True)
            if max_optimizer_steps and optimizer_steps >= max_optimizer_steps:
                break
    finally:
        await env.close()
        server.stop()

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(out_dir))
    tokenizer.save_pretrained(str(out_dir))
    metrics = {
        "reward_mode": reward_mode,
        "model": model_path,
        "sft_adapter": sft_adapter,
        "group_size": group_size,
        "epochs": len(history),
        "total_seconds": round(time.time() - started, 2),
        "history": history,
        "output_dir": str(out_dir),
    }
    (out_dir / "train_metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return metrics


def train_step_grpo(
    sft_adapter: str,
    output_dir: str,
    model_name: str = DEFAULT_MODEL,
    reward_mode: str = "vgdp",
    epochs: int = 3,
    group_size: int = 3,
    lr: float = 1e-5,
    max_steps_per_episode: int = 12,
    ppo_epochs: int = 2,
    seed: int = 42,
    tasks: Optional[List[TaskSpec]] = None,
    max_optimizer_steps: Optional[int] = None,
    semantic: bool = False,
) -> Dict[str, Any]:
    """Synchronous entry point used by the pipeline."""

    return asyncio.run(
        _train_step_grpo_async(
            sft_adapter,
            output_dir,
            model_name=model_name,
            reward_mode=reward_mode,
            epochs=epochs,
            group_size=group_size,
            lr=lr,
            max_steps_per_episode=max_steps_per_episode,
            ppo_epochs=ppo_epochs,
            seed=seed,
            tasks=tasks,
            max_optimizer_steps=max_optimizer_steps,
            semantic=semantic,
        )
    )
