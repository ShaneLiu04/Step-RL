"""DeepSpeed integration wrapper for Step-RL."""

from typing import Any, Dict, Optional

import torch

from step_rl.training.distributed_config import get_deepspeed_config
from step_rl.utils.logging_utils import get_logger

logger = get_logger(__name__)

try:
    import deepspeed

    HAS_DEEPSPEED = True
except ImportError:  # pragma: no cover
    HAS_DEEPSPEED = False
    deepspeed = None  # type: ignore[assignment]


class DeepSpeedStepRLTrainer:
    """Wraps Step-RL training with DeepSpeed ZeRO.

    Parameters
    ----------
    model : torch.nn.Module
        The policy model to train.
    config : Dict[str, Any]
        Full Step-RL config dict.
    """

    def __init__(
        self,
        model: torch.nn.Module,
        config: Dict[str, Any],
        optimizer: Optional[torch.optim.Optimizer] = None,
        lr_scheduler: Optional[Any] = None,
    ):
        if not HAS_DEEPSPEED:
            raise ImportError(
                "DeepSpeed is not installed. Install it with: pip install deepspeed"
            )

        ds_config = get_deepspeed_config(config)
        logger.info(
            f"Initializing DeepSpeed engine with ZeRO stage "
            f"{ds_config['zero_optimization']['stage']}"
        )

        params = model.parameters()
        self.engine, self.optimizer, _, self.lr_scheduler = deepspeed.initialize(
            model=model,
            model_parameters=params,
            config=ds_config,
            optimizer=optimizer,
            lr_scheduler=lr_scheduler,
        )
        logger.info("DeepSpeed engine initialized successfully")

    def train_step(self, batch: Dict[str, torch.Tensor]) -> float:
        """Execute one DeepSpeed training step.

        Parameters
        ----------
        batch :
            Dictionary of tensors forwarded to the model.

        Returns
        -------
        float
            The scalar loss value.
        """
        loss = self.engine(**batch)
        self.engine.backward(loss)
        self.engine.step()
        return loss.item()

    def save_checkpoint(self, save_dir: str, tag: Optional[str] = None) -> None:
        """Save DeepSpeed checkpoint.

        Parameters
        ----------
        save_dir : str
            Directory to save checkpoints into.
        tag : str, optional
            Checkpoint tag (defaults to latest step).
        """
        self.engine.save_checkpoint(save_dir, tag=tag)
        logger.info(f"DeepSpeed checkpoint saved to {save_dir} (tag={tag})")

    def load_checkpoint(self, load_dir: str, tag: Optional[str] = None) -> None:
        """Load DeepSpeed checkpoint.

        Parameters
        ----------
        load_dir : str
            Directory containing checkpoints.
        tag : str, optional
            Checkpoint tag to load.
        """
        self.engine.load_checkpoint(load_dir, tag=tag)
        logger.info(f"DeepSpeed checkpoint loaded from {load_dir} (tag={tag})")
