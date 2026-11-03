"""Real edge-device Agent RL pipeline (AR001).

This package intentionally avoids mock environments and synthetic metrics.
All rewards used for training/evaluation come from a real HTTP service and a
real browser session.
"""

from .site import PRODUCTS, LocalShopServer
from .tasks import EVAL_TASKS, SFT_TASKS, TRAIN_RL_TASKS, TaskSpec
from .verifier import ProgressResult, compute_progress

__all__ = [
    "PRODUCTS",
    "LocalShopServer",
    "TaskSpec",
    "SFT_TASKS",
    "TRAIN_RL_TASKS",
    "EVAL_TASKS",
    "ProgressResult",
    "compute_progress",
]
