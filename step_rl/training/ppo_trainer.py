"""
PPO Trainer for Step-RL v2.0
- Rollout collection with grounding validation
- Progress estimator dense rewards
- State memory loop detection + novelty
- Dynamic reward weighting via curriculum
- GAE advantage estimation
- KL divergence constraint
- Prioritized trajectory replay
- Checkpoint resume

NOTE: This is a custom simplified PPO implementation for research prototyping.
For production use, consider migrating to trl.PPOTrainer which handles
per-token log-prob computation, batched generation, and optimized memory
management out of the box.
"""

import asyncio
from typing import Any, Dict, List, Tuple

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from step_rl.training.base_trainer import (
    BaseTrainer,
    Trajectory,
    _build_base_parser,
    _load_config_and_components,
    logger,
)
from step_rl.training.gae_utils import adaptive_gae_lambda
from step_rl.training.kl_controller import AdaptiveKLController


class ValueHead(nn.Module):
    """Value head on top of LLM last-token hidden states."""

    def __init__(self, hidden_size: int, dropout: float = 0.1):
        super().__init__()
        self.dense = nn.Sequential(
            nn.Linear(hidden_size, 512),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(512, 1),
        )

    def forward(self, last_hidden: torch.Tensor) -> torch.Tensor:
        value = self.dense(last_hidden)
        return value.squeeze(-1)


class PPOTrainer(BaseTrainer):
    """
    PPO training loop for Step-RL v2.0.
    """

    def __init__(
        self,
        policy_model,
        ref_model,
        value_model: nn.Module,
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
            algorithm="ppo",
        )
        self.value_model = value_model.to(device)

        # PPO hyperparameters
        ppo_cfg = config["training"]["ppo"]
        self.clip_range = ppo_cfg["clip_range"]
        self.kl_coef = ppo_cfg["kl_coef"]
        self.kl_target = ppo_cfg["kl_target"]
        self.kl_adaptive = ppo_cfg["kl_adaptive"]
        self.gamma = ppo_cfg["gamma"]
        self.gae_lambda = ppo_cfg["gae_lambda"]
        self.vf_coef = ppo_cfg["vf_coef"]
        self.entropy_coef = ppo_cfg.get("entropy_coef", 0.01)
        self.max_grad_norm = ppo_cfg["max_grad_norm"]
        self.num_epochs_per_update = ppo_cfg["num_epochs_per_update"]
        self.mini_batch_size = ppo_cfg["mini_batch_size"]
        self.policy_lr = ppo_cfg["policy_lr"]
        self.value_lr = ppo_cfg["value_lr"]

        # Step-RL v2.1 extension flags
        self.use_adaptive_gae = ppo_cfg.get("use_adaptive_gae", False)
        self.use_trl_adapter = ppo_cfg.get("use_trl_adapter", False)

        # Adaptive KL controller (replaces simple scalar heuristic when enabled)
        if self.kl_adaptive:
            kl_controller = AdaptiveKLController(
                init_kl_coef=self.kl_coef,
                target_kl=self.kl_target,
            )
            self.setup_kl_controller(kl_controller)
            logger.info(
                f"AdaptiveKLController enabled: init_kl={self.kl_coef}, "
                f"target_kl={self.kl_target}"
            )

        self.policy_optimizer = torch.optim.AdamW(
            self.policy.parameters(), lr=self.policy_lr, weight_decay=0.01
        )
        self.value_optimizer = torch.optim.AdamW(
            self.value_model.parameters(), lr=self.value_lr, weight_decay=0.01
        )

    async def _policy_forward(self, prompt_text: str) -> Dict[str, Any]:
        """Override to include value estimate."""
        result = await super()._policy_forward(prompt_text)

        # Compute value using last non-pad token hidden state of the *prompt*
        inputs = self.tokenizer(
            prompt_text, return_tensors="pt", truncation=True, max_length=4096
        )
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = self.policy(**inputs, output_hidden_states=True)
            hidden = outputs.hidden_states[-1]  # [1, seq_len, hidden]
            last_idx = inputs["attention_mask"].sum(dim=1) - 1
            last_hidden = hidden[0, last_idx[0]]
            value = self.value_model(last_hidden.unsqueeze(0)).item()

        result["value"] = value
        return result

    # -----------------------------
    # GAE
    # -----------------------------

    def compute_gae(self, trajectory: Trajectory) -> Tuple[List[float], List[float]]:
        """Compute GAE advantages and returns.

        When ``use_adaptive_gae`` is enabled the GAE lambda is computed
        dynamically based on training progress and average episode length.
        """
        rewards = np.array(trajectory.rewards, dtype=np.float64)
        values = np.array(trajectory.values, dtype=np.float64)
        dones = np.array(trajectory.dones, dtype=np.float64)
        T = len(rewards)

        # Adaptive lambda override
        if self.use_adaptive_gae:
            gae_lambda = adaptive_gae_lambda(
                epoch=self.epoch,
                total_epochs=self.config["curriculum"]["total_epochs"],
                avg_episode_length=self._avg_episode_length,
            )
        else:
            gae_lambda = self.gae_lambda

        advantages = np.zeros(T, dtype=np.float64)
        returns = np.zeros(T, dtype=np.float64)
        gae = 0.0

        for t in reversed(range(T)):
            if t == T - 1:
                next_value = 0.0
                next_non_terminal = 0.0
            else:
                next_value = values[t + 1]
                next_non_terminal = 1.0 - dones[t]

            delta = rewards[t] + self.gamma * next_value * next_non_terminal - values[t]
            gae = delta + self.gamma * gae_lambda * next_non_terminal * gae
            advantages[t] = gae
            returns[t] = gae + values[t]

        adv_mean = advantages.mean()
        adv_std = advantages.std() + 1e-8
        advantages = (advantages - adv_mean) / adv_std

        return advantages.tolist(), returns.tolist()

    # -----------------------------
    # PPO Update
    # -----------------------------

    def update(self, trajectories: List[Trajectory]) -> Dict[str, float]:
        """
        Run PPO update on collected trajectories.

        Uses the last-token log-prob approximation: both rollout and update
        phases compute the log-probability of the *last generated token*.
        The old log-prob is stored during rollout; the new log-prob is
        recomputed here by concatenating prompt + response and indexing
        the last token with the *actual* sampled token id (not argmax).
        """
        all_obs, all_responses, all_old_log_probs, all_advantages, all_returns = (
            [],
            [],
            [],
            [],
            [],
        )

        for traj in trajectories:
            advantages, returns = self.compute_gae(traj)
            all_obs.extend(traj.observations)
            all_responses.extend(traj.responses)
            all_old_log_probs.extend(traj.log_probs)
            all_advantages.extend(advantages)
            all_returns.extend(returns)

        # Mix replay buffer
        replay_n = int(len(trajectories) * self.replay_ratio)
        replay_trajs = self.sample_replay_trajectories(replay_n)
        for traj in replay_trajs:
            advantages, returns = self.compute_gae(traj)
            all_obs.extend(traj.observations)
            all_responses.extend(traj.responses)
            all_old_log_probs.extend(traj.log_probs)
            all_advantages.extend(advantages)
            all_returns.extend(returns)

        dataset_size = len(all_obs)
        if dataset_size == 0:
            return {}

        metrics = {"policy_loss": 0.0, "value_loss": 0.0, "kl": 0.0, "entropy": 0.0}
        num_updates = 0

        self.policy.train()
        self.value_model.train()
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
                batch_returns = torch.tensor(
                    [all_returns[i] for i in batch_idx],
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

                # PPO surrogate loss
                ratio = torch.exp(new_log_probs - batch_old_log_probs)
                surr1 = ratio * batch_advantages
                surr2 = (
                    torch.clamp(ratio, 1.0 - self.clip_range, 1.0 + self.clip_range)
                    * batch_advantages
                )
                policy_loss = -torch.min(surr1, surr2).mean()

                # Value loss (last-token hidden state)
                hidden = outputs.hidden_states[-1]
                last_hidden = hidden[batch_indices, seq_lengths]
                values = self.value_model(last_hidden)
                value_loss = F.mse_loss(values.squeeze(-1), batch_returns)

                loss = (
                    policy_loss
                    + self.vf_coef * value_loss
                    + self.kl_coef * kl
                    - self.entropy_coef * entropy
                )

                self.policy_optimizer.zero_grad()
                self.value_optimizer.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(
                    self.policy.parameters(), self.max_grad_norm
                )
                torch.nn.utils.clip_grad_norm_(
                    self.value_model.parameters(), self.max_grad_norm
                )
                self.policy_optimizer.step()
                self.value_optimizer.step()

                metrics["policy_loss"] += policy_loss.item()
                metrics["value_loss"] += value_loss.item()
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
            "value_state_dict": self.value_model.state_dict(),
            "policy_optimizer": self.policy_optimizer.state_dict(),
            "value_optimizer": self.value_optimizer.state_dict(),
            "kl_coef": self.kl_coef,
            "algorithm": "ppo",
        }
        if self.kl_controller is not None:
            ckpt["kl_controller_state"] = self.kl_controller.state_dict()
        torch.save(ckpt, path)
        logger.info(f"Checkpoint saved: {path}")

    def load_checkpoint(self, path: str) -> None:  # noqa: D401
        ckpt = torch.load(path, map_location=self.device, weights_only=True)
        self.policy.load_state_dict(ckpt["policy_state_dict"])
        self.value_model.load_state_dict(ckpt["value_state_dict"])
        self.policy_optimizer.load_state_dict(ckpt["policy_optimizer"])
        self.value_optimizer.load_state_dict(ckpt["value_optimizer"])
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
    parser = _build_base_parser("PPO Training for Step-RL")
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
    ) = _load_config_and_components(args, "ppo")

    value_model = ValueHead(policy.config.hidden_size)

    trainer = PPOTrainer(
        policy_model=policy,
        ref_model=ref_model,
        value_model=value_model,
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
