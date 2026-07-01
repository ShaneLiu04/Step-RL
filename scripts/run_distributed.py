#!/usr/bin/env python
"""Launch distributed training for Step-RL."""

import argparse
import os
import subprocess

import torch
import torch.distributed as dist


def setup_distributed(rank: int, world_size: int, backend: str = "nccl") -> None:
    """Initialize the distributed process group.

    Parameters
    ----------
    rank : int
        Rank of the current process.
    world_size : int
        Total number of processes.
    backend : str
        PyTorch distributed backend (default ``nccl`` for CUDA).
    """
    os.environ["MASTER_ADDR"] = os.environ.get("MASTER_ADDR", "localhost")
    os.environ["MASTER_PORT"] = os.environ.get("MASTER_PORT", "12355")
    dist.init_process_group(backend, rank=rank, world_size=world_size)


def run_ddp(rank: int, world_size: int, config_path: str, algorithm: str) -> None:
    """DDP training worker entry point.

    Parameters
    ----------
    rank : int
        Process rank.
    world_size : int
        Total number of processes.
    config_path : str
        Path to the Step-RL ``config.yaml``.
    algorithm : str
        RL algorithm to use (``ppo`` or ``grpo``).
    """
    setup_distributed(rank, world_size, backend="nccl")
    torch.cuda.set_device(rank)

    # Import inside the worker so each process gets its own model copy
    if algorithm == "grpo":
        from step_rl.training.grpo_trainer import (
            GRPOTrainer,
            _load_config_and_components,
        )
    else:
        from step_rl.training.ppo_trainer import PPOTrainer, _load_config_and_components

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
    ) = _load_config_and_components(
        argparse.Namespace(config=config_path, resume=None, output_dir="./outputs"),
        algorithm,
    )

    device = torch.device(f"cuda:{rank}")
    policy = policy.to(device)
    ref_model = ref_model.to(device)

    if algorithm == "grpo":
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
    else:
        trainer = PPOTrainer(
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

    import asyncio

    asyncio.run(trainer.train(config["curriculum"]["total_epochs"], "./outputs"))
    dist.destroy_process_group()


def run_fsdp(rank: int, world_size: int, config_path: str, algorithm: str) -> None:
    """FSDP training worker entry point.

    Wraps the policy model with :class:`torch.distributed.fsdp.FullyShardedDataParallel`
    and runs training.
    """
    setup_distributed(rank, world_size, backend="nccl")
    torch.cuda.set_device(rank)

    from torch.distributed.fsdp import FullyShardedDataParallel as FSDP
    from torch.distributed.fsdp import ShardingStrategy

    from step_rl.training.distributed_config import get_fsdp_config

    if algorithm == "grpo":
        from step_rl.training.grpo_trainer import (
            GRPOTrainer,
            _load_config_and_components,
        )
    else:
        from step_rl.training.ppo_trainer import (
            PPOTrainer,
            _load_config_and_components,
        )

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
    ) = _load_config_and_components(
        argparse.Namespace(config=config_path, resume=None, output_dir="./outputs"),
        algorithm,
    )

    device = torch.device(f"cuda:{rank}")
    fsdp_cfg = get_fsdp_config(config)

    policy = FSDP(
        policy.to(device),
        mixed_precision=fsdp_cfg["mixed_precision"],
        use_orig_params=fsdp_cfg["use_orig_params"],
        limit_all_gathers=fsdp_cfg["limit_all_gathers"],
        sharding_strategy=ShardingStrategy.FULL_SHARD,
        device_id=device,
    )
    ref_model = ref_model.to(device)

    if algorithm == "grpo":
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
    else:
        trainer = PPOTrainer(
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

    import asyncio

    asyncio.run(trainer.train(config["curriculum"]["total_epochs"], "./outputs"))
    dist.destroy_process_group()


def main() -> None:
    """CLI entry point for launching distributed training."""
    parser = argparse.ArgumentParser(
        description="Launch distributed training for Step-RL"
    )
    parser.add_argument(
        "--config", type=str, default="config.yaml", help="Path to config.yaml"
    )
    parser.add_argument(
        "--world_size", type=int, default=1, help="Number of GPU processes"
    )
    parser.add_argument(
        "--algorithm",
        type=str,
        default="grpo",
        choices=["ppo", "grpo"],
        help="RL algorithm to train",
    )
    parser.add_argument(
        "--backend",
        type=str,
        default="deepspeed",
        choices=["deepspeed", "fsdp", "ddp"],
        help="Distributed training backend",
    )
    args = parser.parse_args()

    world_size = args.world_size

    if args.backend == "deepspeed":
        # DeepSpeed handles its own distributed setup via launcher
        cmd = [
            "deepspeed",
            "--num_gpus",
            str(world_size),
            "-m",
            f"step_rl.training.{args.algorithm}_trainer",
            "--config",
            args.config,
        ]
        print(f"[run_distributed] Launching: {' '.join(cmd)}")
        subprocess.run(cmd, check=True)

    elif args.backend == "fsdp":
        import torch.multiprocessing as mp

        mp.spawn(
            run_fsdp,
            args=(world_size, args.config, args.algorithm),
            nprocs=world_size,
            join=True,
        )
    else:
        import torch.multiprocessing as mp

        mp.spawn(
            run_ddp,
            args=(world_size, args.config, args.algorithm),
            nprocs=world_size,
            join=True,
        )


if __name__ == "__main__":
    main()
