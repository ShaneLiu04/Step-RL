"""Robust checkpoint management with atomic save and automatic recovery."""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import torch

from step_rl.utils.logging_utils import get_logger

logger = get_logger(__name__)


class CheckpointManager:
    """Atomic checkpoint save/load with corruption recovery."""

    def __init__(self, save_dir: str = "./checkpoints", keep_last_n: int = 5):
        self.save_dir = Path(save_dir)
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self.keep_last_n = keep_last_n

    def save(self, state: Dict[str, Any], tag: str = "latest") -> str:
        """Atomic save: write to temp, then rename."""
        save_path = self.save_dir / f"checkpoint_{tag}.pt"
        temp_path = self.save_dir / f"checkpoint_{tag}.tmp"

        try:
            torch.save(state, temp_path)
            # Atomic rename (Windows-compatible)
            if save_path.exists():
                save_path.unlink()
            temp_path.rename(save_path)
            logger.info(f"Checkpoint saved: {save_path}")

            # Cleanup old checkpoints
            self._cleanup_old()
            return str(save_path)
        except Exception as e:
            logger.error(f"Checkpoint save failed: {e}")
            if temp_path.exists():
                temp_path.unlink()
            raise

    def load(self, tag: str = "latest") -> Optional[Dict[str, Any]]:
        """Load with validation and corruption detection."""
        save_path = self.save_dir / f"checkpoint_{tag}.pt"

        if not save_path.exists():
            logger.warning(f"No checkpoint found at {save_path}")
            return None

        try:
            state = torch.load(save_path, map_location="cpu", weights_only=True)

            # Normalize for backward compatibility with base_trainer.py
            if "policy_state_dict" in state and "policy_state" not in state:
                state["policy_state"] = state["policy_state_dict"]

            # Validate required keys
            required_keys = ["policy_state", "global_step", "epoch"]
            missing = [k for k in required_keys if k not in state]
            if missing:
                logger.error(f"Checkpoint corrupt: missing keys {missing}")
                return None

            logger.info(
                f"Checkpoint loaded: {save_path}, "
                f"epoch={state['epoch']}, step={state['global_step']}"
            )
            return state
        except Exception as e:
            logger.error(f"Checkpoint load failed: {e}. Starting from scratch.")
            # Try to recover from backup
            backup = self._find_backup(tag)
            if backup:
                logger.info(f"Attempting recovery from backup: {backup}")
                return torch.load(backup, map_location="cpu", weights_only=True)
            return None

    def _cleanup_old(self):
        """Keep only the last N checkpoints."""
        checkpoints = sorted(
            self.save_dir.glob("checkpoint_*.pt"), key=os.path.getmtime
        )
        if len(checkpoints) > self.keep_last_n:
            for old_ckpt in checkpoints[: -self.keep_last_n]:
                old_ckpt.unlink()
                logger.info(f"Removed old checkpoint: {old_ckpt}")

    def _find_backup(self, tag: str) -> Optional[Path]:
        """Find a backup checkpoint if main is corrupt."""
        backups = sorted(
            self.save_dir.glob(f"checkpoint_{tag}_*.pt"), key=os.path.getmtime
        )
        return backups[-1] if backups else None

    def list_checkpoints(self) -> List[str]:
        """List all available checkpoints."""
        return [str(p.name) for p in sorted(self.save_dir.glob("checkpoint_*.pt"))]

    def auto_resume(self, trainer) -> bool:
        """Attempt to auto-resume from latest checkpoint."""
        state = self.load("latest")
        if state is None:
            return False

        try:
            # Try both key names for compatibility with base_trainer.py
            policy_state = state.get("policy_state") or state.get("policy_state_dict")
            if policy_state is not None:
                trainer.policy.load_state_dict(policy_state)
            if hasattr(trainer, "policy_optimizer") and "optimizer_state" in state:
                trainer.policy_optimizer.load_state_dict(state["optimizer_state"])
            trainer.global_step = state.get("global_step", 0)
            trainer.epoch = state.get("epoch", 0)

            # Restore KL controller if present
            if hasattr(trainer, "kl_controller") and "kl_controller_state" in state:
                trainer.kl_controller.load_state_dict(state["kl_controller_state"])

            logger.info(
                f"Auto-resumed from epoch {trainer.epoch}, "
                f"step {trainer.global_step}"
            )
            return True
        except Exception as e:
            logger.error(f"Auto-resume failed: {e}")
            return False
