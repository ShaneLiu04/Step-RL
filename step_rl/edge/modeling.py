"""Model loading helpers shared by SFT / rollout / evaluation."""

from __future__ import annotations

import os
import random
from glob import glob
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import torch

DEFAULT_MODEL = os.environ.get("STEP_RL_MODEL", "Qwen/Qwen3-0.6B-Base")


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def resolve_model_path(name: str = DEFAULT_MODEL) -> str:
    path = Path(name)
    if path.exists():
        return str(path)
    cache = Path.home() / ".cache" / "huggingface" / "hub"
    if "/" in name:
        org, repo = name.split("/", 1)
        folder = cache / f"models--{org}--{repo}"
        snapshots = sorted(glob(str(folder / "snapshots" / "*" / "config.json")))
        if snapshots:
            return str(Path(snapshots[0]).parent)
    return name


def get_device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def load_tokenizer(model_path: str):
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(
        model_path, trust_remote_code=False, use_fast=True
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    return tokenizer


def load_base_model(model_path: str, dtype: Optional[torch.dtype] = None):
    from transformers import AutoModelForCausalLM

    dtype = dtype or (torch.float16 if torch.cuda.is_available() else torch.float32)
    model = AutoModelForCausalLM.from_pretrained(
        model_path,
        dtype=dtype,
        low_cpu_mem_usage=True,
        trust_remote_code=False,
    )
    model.config.use_cache = False
    return model.to(get_device())


def load_policy(
    model_path: str,
    adapter_path: Optional[str] = None,
    trainable: bool = False,
    dtype: Optional[torch.dtype] = None,
) -> Tuple[torch.nn.Module, object]:
    """Load base + optional LoRA adapter.  Returns (model, tokenizer)."""

    tokenizer = load_tokenizer(model_path)
    model = load_base_model(model_path, dtype=dtype)
    if adapter_path:
        from peft import PeftModel

        model = PeftModel.from_pretrained(model, adapter_path, is_trainable=trainable)
        model = model.to(get_device())
    if trainable:
        model.train()
    else:
        model.eval()
    return model, tokenizer


def lora_config(r: int = 16, alpha: int = 32, dropout: float = 0.05):
    from peft import LoraConfig

    return LoraConfig(
        r=r,
        lora_alpha=alpha,
        lora_dropout=dropout,
        target_modules="all-linear",
        bias="none",
        task_type="CAUSAL_LM",
    )
