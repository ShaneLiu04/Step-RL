"""Step-RL TRL official Trainer wrapper adapters.

Provides optional drop-in wrappers around ``trl.PPOTrainer`` and
``trl.GRPOTrainer`` that inject Step-RL's custom reward composition stack.

Usage
-----
These adapters are **optional**.  When ``trl`` is not installed the classes
are still importable but will raise ``RuntimeError`` on instantiation.
Enable them via the trainer config flag ``use_trl_adapter: true``.
"""

from typing import Any, Callable, Dict, List

import torch

try:
    from trl import GRPOConfig, GRPOTrainer, PPOConfig, PPOTrainer

    _TRL_AVAILABLE = True
except ImportError:  # pragma: no cover
    _TRL_AVAILABLE = False
    # Dummy bases so the module remains importable even without trl installed.
    PPOTrainer = object  # type: ignore[misc,assignment]
    PPOConfig = object  # type: ignore[misc,assignment]
    GRPOTrainer = object  # type: ignore[misc,assignment]
    GRPOConfig = object  # type: ignore[misc,assignment]


def is_trl_available() -> bool:
    """Return whether the ``trl`` library is installed."""
    return _TRL_AVAILABLE


class StepRLPPOAdapter(PPOTrainer):  # type: ignore[misc]
    """Wraps ``trl.PPOTrainer`` with Step-RL custom reward composition.

    Parameters
    ----------
    config :
        Full Step-RL config dict (must contain ``training.ppo``).
    reward_fn :
        Callable with signature ``(queries, responses, **kwargs) -> rewards``.
    *args, **kwargs :
        Forwarded to ``trl.PPOTrainer`` (e.g. ``model``, ``ref_model``, …).
    """

    def __init__(
        self,
        config: Dict[str, Any],
        reward_fn: Callable,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        if not _TRL_AVAILABLE:
            raise RuntimeError("trl is not installed. Install it with: pip install trl")

        ppo_cfg = config["training"]["ppo"]
        ppo_config = PPOConfig(
            model_name=config["model"]["base_model"],
            learning_rate=float(ppo_cfg["policy_lr"]),
            batch_size=config["training"]["batch_size"],
            mini_batch_size=ppo_cfg["mini_batch_size"],
            gradient_accumulation_steps=config["training"].get(
                "gradient_accumulation_steps", 4
            ),
            optimize_cuda_cache=True,
            early_stopping=True,
            target_kl=float(ppo_cfg.get("kl_target", 0.1)),
            ppo_epochs=ppo_cfg.get("num_epochs_per_update", 4),
            clip_eps=float(ppo_cfg.get("clip_range", 0.2)),
            vf_coef=float(ppo_cfg.get("vf_coef", 0.5)),
            entropy_coef=float(ppo_cfg.get("entropy_coef", 0.01)),
        )
        super().__init__(config=ppo_config, *args, **kwargs)
        self._custom_reward_fn = reward_fn
        self._step_rl_config = config

    def compute_rewards(
        self,
        queries: List[torch.LongTensor],
        responses: List[torch.LongTensor],
        **kwargs: Any,
    ) -> List[torch.FloatTensor]:
        """Override to inject custom reward composition.

        Parameters
        ----------
        queries :
            List of prompt token-id tensors.
        responses :
            List of response token-id tensors.
        **kwargs :
            Extra metadata forwarded from ``trl``.

        Returns
        -------
        List[torch.FloatTensor]
            Scalar reward tensor for each query/response pair.
        """
        return self._custom_reward_fn(queries, responses, **kwargs)


class StepRLGRPOAdapter(GRPOTrainer):  # type: ignore[misc]
    """Wraps ``trl.GRPOTrainer`` with Step-RL custom reward composition.

    Parameters
    ----------
    config :
        Full Step-RL config dict (must contain ``training.grpo``).
    reward_fn :
        Callable with signature ``(queries, responses, **kwargs) -> rewards``.
    *args, **kwargs :
        Forwarded to ``trl.GRPOTrainer``.
    """

    def __init__(
        self,
        config: Dict[str, Any],
        reward_fn: Callable,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        if not _TRL_AVAILABLE:
            raise RuntimeError("trl is not installed. Install it with: pip install trl")

        grpo_cfg = config["training"]["grpo"]
        grpo_config = GRPOConfig(
            model_name=config["model"]["base_model"],
            learning_rate=float(grpo_cfg["policy_lr"]),
            batch_size=config["training"]["batch_size"],
            optimize_cuda_cache=True,
        )
        super().__init__(config=grpo_config, *args, **kwargs)
        self._custom_reward_fn = reward_fn
        self._step_rl_config = config

    def compute_rewards(
        self,
        queries: List[torch.LongTensor],
        responses: List[torch.LongTensor],
        **kwargs: Any,
    ) -> List[torch.FloatTensor]:
        """Override to inject custom reward composition.

        Parameters
        ----------
        queries :
            List of prompt token-id tensors.
        responses :
            List of response token-id tensors.
        **kwargs :
            Extra metadata forwarded from ``trl``.

        Returns
        -------
        List[torch.FloatTensor]
            Scalar reward tensor for each query/response pair.
        """
        return self._custom_reward_fn(queries, responses, **kwargs)
