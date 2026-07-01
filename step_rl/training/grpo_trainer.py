"""
GRPO Trainer for Step-RL v2.0
- Group Relative Policy Optimization (no value model needed)
- Uses group mean as baseline for advantage estimation
- Saves ~30% VRAM compared to PPO

NOTE: This is a custom simplified GRPO implementation for research prototyping.
For production use, consider migrating to trl.GRPOTrainer which handles
per-token log-prob computation, batched generation, and optimized memory
management out of the box.
"""

import asyncio
from typing import Any, Dict, List

import numpy as np
import torch
import torch.nn.functional as F

from step_rl.training.base_trainer import (
    BaseTrainer,
    Trajectory,
    _build_base_parser,
    _load_config_and_components,
    logger,
)
from step_rl.training.kl_controller import AdaptiveKLController
from step_rl.training.trl_adapters import is_trl_available, StepRLGRPOAdapter


class GRPOTrainer(BaseTrainer):
    """
    GRPO (Group Relative Policy Optimization) trainer.
    Advantages computed as group-normalized returns.
    """

    def __init__(
        self,
        policy_model,
        ref_model,
        tokenizer,
        grounding_validator,
        progress_estimator,
        state_memory,
        curriculum,
        env,
        config: Dict[str, Any],
        device: torch.device,
    ):
        super().__init__(
            policy_model=policy_model,
            ref_model=ref_model,
            tokenizer=tokenizer,
            grounding_validator=grounding_validator,
            progress_estimator=progress_estimator,
            state_memory=state_memory,
            curriculum=curriculum,
            env=env,
            config=config,
            device=device,
            algorithm="grpo",
        )

        # GRPO hyperparameters — FIXED: read from grpo section, not ppo
        grpo_cfg = config["training"]["grpo"]
        self.group_size = grpo_cfg["group_size"]
        self.clip_range = grpo_cfg["clip_range"]
        self.kl_coef = grpo_cfg["kl_coef"]
        self.kl_target = grpo_cfg.get("kl_target", 0.1)
        self.kl_adaptive = grpo_cfg.get("kl_adaptive", False)
        self.gamma = grpo_cfg["gamma"]
        self.policy_lr = grpo_cfg["policy_lr"]
        self.max_grad_norm = grpo_cfg.get("max_grad_norm", 1.0)
        self.num_epochs_per_update = grpo_cfg.get("num_epochs_per_update", 4)
        self.mini_batch_size = grpo_cfg.get("mini_batch_size", 2)

        # Step-RL v2.1 extension flags
        self.use_trl_adapter = grpo_cfg.get("use_trl_adapter", False)

        # Adaptive KL controller (optional, backward-compatible)
        if self.kl_adaptive:
            kl_controller = AdaptiveKLController(
                init_kl_coef=self.kl_coef,
                target_kl=self.kl_target,
            )
            self.setup_kl_controller(kl_controller)
            logger.info(
                f"AdaptiveKLController enabled for GRPO: init_kl={self.kl_coef}, "
                f"target_kl={self.kl_target}"
            )

        self.policy_optimizer = torch.optim.AdamW(
            self.policy.parameters(), lr=self.policy_lr, weight_decay=0.01
        )

    # -----------------------------
    # GRPO Advantage (Group Normalized)
    # -----------------------------

    def compute_group_advantages(
        self, trajectories: List[Trajectory]
    ) -> List[List[float]]:
        """
        Group trajectories and compute advantages as normalized returns.
        Each step within a trajectory receives the same advantage = normalized group return.
        """
        all_advantages = []
        for i in range(0, len(trajectories), self.group_size):
            group = trajectories[i : i + self.group_size]
            returns = [t.total_return for t in group]
            mean_r = np.mean(returns)
            std_r = np.std(returns) + 1e-8
            for t in group:
                A = (t.total_return - mean_r) / std_r
                all_advantages.append([A] * t.length)
        return all_advantages

    # -----------------------------
    # GRPO Update
    # -----------------------------

    def update(self, trajectories: List[Trajectory]) -> Dict[str, float]:
        """
        Run GRPO update on collected trajectories.

        Uses the last-token log-prob approximation: both rollout and update
        phases compute the log-probability of the *last generated token*.
        The old log-prob is stored during rollout; the new log-prob is
        recomputed here by concatenating prompt + response and indexing
        the last token with the *actual* sampled token id (not argmax).
        """
        advantages_per_traj = self.compute_group_advantages(trajectories)

        all_obs, all_responses, all_old_log_probs, all_advantages = [], [], [], []
        for traj, advs in zip(trajectories, advantages_per_traj):
            all_obs.extend(traj.observations)
            all_responses.extend(traj.responses)
            all_old_log_probs.extend(traj.log_probs)
            all_advantages.extend(advs)

        # Mix replay
        replay_n = int(len(trajectories) * self.replay_ratio)
        replay_trajs = self.sample_replay_trajectories(replay_n)
        if replay_trajs:
            replay_advantages = self.compute_group_advantages(replay_trajs)
            for traj, advs in zip(replay_trajs, replay_advantages):
                all_obs.extend(traj.observations)
                all_responses.extend(traj.responses)
                all_old_log_probs.extend(traj.log_probs)
                all_advantages.extend(advs)

        dataset_size = len(all_obs)
        if dataset_size == 0:
            return {}

        metrics = {"policy_loss": 0.0, "kl": 0.0, "entropy": 0.0}
        num_updates = 0

        self.policy.train()
        self.ref_model.eval()

        for _ in range(self.num_epochs_per_update):
            indices = np.random.permutation(dataset_size)
            for start in range(0, dataset_size, self.mini_batch_size):
                end = min(start + self.mini_batch_size, dataset_size)
                batch_idx = indices[start:end]

                batch_obs = [all_obs[i] for i in batch_idx]
                batch_responses = [all_responses[i] for i in batch_idx]
                batch_advantages = torch.tensor(
                    [all_advantages[i] for i in batch_idx],
                    dtype=torch.float32,
                    device=self.device,
                )
                batch_old_log_probs = torch.tensor(
                    [all_old_log_probs[i] for i in batch_idx],
                    dtype=torch.float32,
                    device=self.device,
                )

                # Compute new log-prob of the *last generated token* under current policy
                new_log_probs = self._get_update_log_probs(batch_obs, batch_responses)

                # KL with reference (last-token approximation)
                inputs = self.tokenizer(
                    [obs + resp for obs, resp in zip(batch_obs, batch_responses)],
                    return_tensors="pt",
                    padding=True,
                    truncation=True,
                    max_length=4096,
                )
                inputs = {k: v.to(self.device) for k, v in inputs.items()}
                seq_lengths = inputs["attention_mask"].sum(dim=1) - 1
                batch_indices = torch.arange(
                    inputs["input_ids"].size(0), device=self.device
                )

                outputs = self.policy(**inputs, output_hidden_states=True)
                last_logits = outputs.logits[batch_indices, seq_lengths]

                dist = torch.distributions.Categorical(logits=last_logits)
                entropy = dist.entropy().mean()

                with torch.no_grad():
                    ref_outputs = self.ref_model(**inputs)
                    ref_last_logits = ref_outputs.logits[batch_indices, seq_lengths]

                kl = F.kl_div(
                    F.log_softmax(last_logits, dim=-1),
                    F.softmax(ref_last_logits, dim=-1),
                    reduction="batchmean",
                )

                # GRPO surrogate
                ratio = torch.exp(new_log_probs - batch_old_log_probs)
                surr1 = ratio * batch_advantages
                surr2 = (
                    torch.clamp(ratio, 1.0 - self.clip_range, 1.0 + self.clip_range)
                    * batch_advantages
                )
                policy_loss = -torch.min(surr1, surr2).mean()

                loss = policy_loss + self.kl_coef * kl - 0.01 * entropy

                self.policy_optimizer.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(
                    self.policy.parameters(), self.max_grad_norm
                )
                self.policy_optimizer.step()

                metrics["policy_loss"] += policy_loss.item()
                metrics["kl"] += kl.item()
                metrics["entropy"] += entropy.item()
                num_updates += 1

        for k in metrics:
            metrics[k] /= max(num_updates, 1)

        # Adaptive KL — use AdaptiveKLController if mounted, else fall back to scalar heuristic
        if self.kl_controller is not None:
            updated_kl_coef = self.kl_controller.update(metrics["kl"])
            self.kl_coef = updated_kl_coef
            metrics["kl_coef"] = updated_kl_coef
        elif self.kl_adaptive:
            if metrics["kl"] > self.kl_target * 2:
                self.kl_coef *= 1.5
            elif metrics["kl"] < self.kl_target / 2:
                self.kl_coef /= 1.5
            self.kl_coef = max(0.01, min(self.kl_coef, 1.0))
            metrics["kl_coef"] = self.kl_coef

        return metrics

    # -----------------------------
    # Checkpointing (extend base)
    # -----------------------------

    def save_checkpoint(self, save_dir: str, epoch: int) -> None:  # noqa: D401
        path = f"{save_dir}/checkpoint_epoch_{epoch}.pt"
        ckpt = {
            "epoch": epoch,
            "global_step": self.global_step,
            "policy_state_dict": self.policy.state_dict(),
            "policy_optimizer": self.policy_optimizer.state_dict(),
            "kl_coef": self.kl_coef,
            "algorithm": "grpo",
        }
        if self.kl_controller is not None:
            ckpt["kl_controller_state"] = self.kl_controller.state_dict()
        torch.save(ckpt, path)
        logger.info(f"Checkpoint saved: {path}")

    def load_checkpoint(self, path: str) -> None:  # noqa: D401
        ckpt = torch.load(path, map_location=self.device, weights_only=True)
        self.policy.load_state_dict(ckpt["policy_state_dict"])
        self.policy_optimizer.load_state_dict(ckpt["policy_optimizer"])
        self.epoch = ckpt["epoch"]
        self.global_step = ckpt["global_step"]
        self.kl_coef = ckpt.get("kl_coef", self.kl_coef)
        if self.kl_controller is not None and "kl_controller_state" in ckpt:
            self.kl_controller.load_state_dict(ckpt["kl_controller_state"])
        logger.info(f"Checkpoint loaded: {path}")


# -----------------------------
# Entry point
# -----------------------------


def main():
    parser = _build_base_parser("GRPO Training for Step-RL")
    args = parser.parse_args()

    (
        config,
        device,
        env,
        grounding,
        state_memory,
        curriculum,
        tokenizer,
        policy,
        ref_model,
        progress_estimator,
    ) = _load_config_and_components(args, "grpo")

    trainer = GRPOTrainer(
        policy_model=policy,
        ref_model=ref_model,
        tokenizer=tokenizer,
        grounding_validator=grounding,
        progress_estimator=progress_estimator,
        state_memory=state_memory,
        curriculum=curriculum,
        env=env,
        config=config,
        device=device,
    )

    if args.resume:
        trainer.load_checkpoint(args.resume)

    asyncio.run(trainer.train(config["curriculum"]["total_epochs"], args.output_dir))


if __name__ == "__main__":
    main()
