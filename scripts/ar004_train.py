"""AR004: build semantic trajectories, train semantic adapters, run eval."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from step_rl.edge.expert import collect_expert_trajectories  # noqa: E402
from step_rl.edge.modeling import DEFAULT_MODEL  # noqa: E402
from step_rl.edge.sft import run_sft  # noqa: E402
from step_rl.edge.site import LocalShopServer  # noqa: E402
from step_rl.edge.step_grpo import train_step_grpo  # noqa: E402
from step_rl.edge.tasks import SFT_TASKS, TRAIN_RL_TASKS  # noqa: E402

OUT = ROOT / "outputs" / "ar004"
DATA = OUT / "expert_semantic.jsonl"
SFT = OUT / "sft_semantic"
VGDP = OUT / "grpo_semantic_vgdp"
SPARSE = OUT / "grpo_semantic_sparse"


def stage_data(repeats: int) -> None:
    server = LocalShopServer().start()
    try:
        stats = asyncio.run(
            collect_expert_trajectories(
                server.base_url,
                str(DATA),
                tasks=SFT_TASKS,
                repeats=repeats,
                max_steps=12,
                semantic=True,
            )
        )
    finally:
        server.stop()
    print(json.dumps(stats, ensure_ascii=False, indent=2))


def stage_sft(epochs: int, model: str) -> None:
    print(
        json.dumps(
            run_sft(str(DATA), str(SFT), model_name=model, epochs=epochs),
            ensure_ascii=False,
            indent=2,
        )
    )


def stage_rl(epochs: int, group: int, model: str) -> None:
    tasks = [TRAIN_RL_TASKS[0], TRAIN_RL_TASKS[1]]
    for mode, out in (("sparse", SPARSE), ("vgdp", VGDP)):
        print(f"[train] semantic {mode}", flush=True)
        metrics = train_step_grpo(
            str(SFT),
            str(out),
            model_name=model,
            reward_mode=mode,
            epochs=epochs,
            group_size=group,
            max_steps_per_episode=6,
            ppo_epochs=1,
            tasks=tasks,
            semantic=True,
        )
        print(json.dumps(metrics, ensure_ascii=False)[:800])


def main() -> None:
    parser = argparse.ArgumentParser(description="AR004 semantic pipeline")
    parser.add_argument(
        "--stage",
        choices=["data", "sft", "rl", "eval", "all"],
        default="all",
    )
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--sft_epochs", type=int, default=1)
    parser.add_argument("--rl_epochs", type=int, default=2)
    parser.add_argument("--group_size", type=int, default=3)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    if args.stage in ("data", "all"):
        stage_data(args.repeats)
    if args.stage in ("sft", "all"):
        stage_sft(args.sft_epochs, args.model)
    if args.stage in ("rl", "all"):
        stage_rl(args.rl_epochs, args.group_size, args.model)
    if args.stage in ("eval", "all"):
        import subprocess

        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "ar004_eval.py")],
            check=True,
        )


if __name__ == "__main__":
    main()
