"""Inference engine for Step-RL v3.0.

Multi-backend model abstraction supporting HuggingFace, vLLM, and GPT-4o (API).
"""

from step_rl.inference.model_backend import (
    PolicyModelBackend,
    HuggingFaceBackend,
    create_backend,
)

try:
    from step_rl.inference.lora_utils import merge_lora_weights
except ImportError:
    merge_lora_weights = None

__all__ = [
    "PolicyModelBackend",
    "HuggingFaceBackend",
    "create_backend",
    "merge_lora_weights",
]
