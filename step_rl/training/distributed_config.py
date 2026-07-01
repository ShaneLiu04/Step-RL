"""Distributed training configuration for DeepSpeed and FSDP."""

from typing import Any, Dict

import torch


def get_deepspeed_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Generate DeepSpeed ZeRO config from Step-RL config.

    Parameters
    ----------
    config :
        Full Step-RL config dict.

    Returns
    -------
    Dict[str, Any]
        DeepSpeed JSON-compatible configuration dict.
    """
    train_cfg = config["training"]
    algo = train_cfg.get("algorithm", "grpo")

    # Pick learning rate from the active algorithm section
    if algo == "ppo" and "ppo" in train_cfg:
        policy_lr = float(train_cfg["ppo"]["policy_lr"])
    elif algo == "grpo" and "grpo" in train_cfg:
        policy_lr = float(train_cfg["grpo"]["policy_lr"])
    else:
        policy_lr = 1e-5

    grad_accum = train_cfg.get("gradient_accumulation_steps", 4)
    batch_size = train_cfg.get("batch_size", 8)
    dtype = config.get("model", {}).get("dtype", "bf16")

    return {
        "train_batch_size": batch_size * grad_accum,
        "gradient_accumulation_steps": grad_accum,
        "optimizer": {
            "type": "AdamW",
            "params": {
                "lr": policy_lr,
                "weight_decay": 0.01,
                "betas": [0.9, 0.999],
                "eps": 1e-8,
            },
        },
        "scheduler": {
            "type": "WarmupLR",
            "params": {
                "warmup_min_lr": 0,
                "warmup_max_lr": policy_lr,
                "warmup_num_steps": 100,
            },
        },
        "zero_optimization": {
            "stage": 2,
            "offload_optimizer": {"device": "cpu", "pin_memory": True},
            "allgather_partitions": True,
            "allgather_bucket_size": 2e8,
            "overlap_comm": True,
            "reduce_scatter": True,
            "reduce_bucket_size": 2e8,
            "contiguous_gradients": True,
        },
        "bf16": {"enabled": dtype == "bf16"},
        "fp16": {
            "enabled": dtype == "fp16",
            "loss_scale": 0,
            "loss_scale_window": 1000,
            "initial_scale_power": 16,
            "hysteresis": 2,
            "min_loss_scale": 1,
        },
        "gradient_clipping": train_cfg.get("max_grad_norm", 1.0),
        "steps_per_print": train_cfg.get("logging_steps", 10),
    }


def get_fsdp_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Generate FSDP config.

    Parameters
    ----------
    config :
        Full Step-RL config dict.

    Returns
    -------
    Dict[str, Any]
        Dictionary with ``mixed_precision`` policy and other FSDP flags.
    """
    from torch.distributed.fsdp import MixedPrecision

    dtype = config.get("model", {}).get("dtype", "bf16")
    if dtype == "bf16":
        param_dtype = torch.bfloat16
    elif dtype == "fp16":
        param_dtype = torch.float16
    else:
        param_dtype = torch.float32

    return {
        "mixed_precision": MixedPrecision(
            param_dtype=param_dtype,
            reduce_dtype=param_dtype,
            buffer_dtype=torch.float32,
        ),
        "use_orig_params": True,
        "limit_all_gathers": True,
    }
