"""End-to-end real pipeline for AR001.

Stages:
  data    collect expert trajectories through a real browser
  sft     LoRA SFT on real trajectories
  rl      run sparse GRPO and VGDP GRPO
  eval    evaluate the four combinations on held-out tasks
  all     data -> sft -> rl -> eval

No mock environment and no synthetic metrics are used anywhere.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import torch  # noqa: E402

from step_rl.edge.evaluate import run_matrix  # noqa: E402
from step_rl.edge.expert import collect_expert_trajectories  # noqa: E402
from step_rl.edge.modeling import DEFAULT_MODEL  # noqa: E402
from step_rl.edge.sft import run_sft  # noqa: E402
from step_rl.edge.site import LocalShopServer  # noqa: E402
from step_rl.edge.step_grpo import train_step_grpo  # noqa: E402

OUTPUT = ROOT / "outputs" / "ar001"
SFT_DATA = OUTPUT / "expert_sft.jsonl"
SFT_ADAPTER = OUTPUT / "sft_adapter"
GRPO_SPARSE = OUTPUT / "grpo_sparse"
GRPO_VGDP = OUTPUT / "grpo_vgdp"


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except Exception:
        return "unknown"


def _manifest(stage: str, payload: Dict[str, Any]) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / "run_manifest.json"
    data = []
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    data.append(
        {
            "stage": stage,
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "commit": _git_commit(),
            "python": sys.version.split()[0],
            "torch": torch.__version__,
            "cuda": torch.cuda.is_available(),
            "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "",
            "platform": platform.platform(),
            **payload,
        }
    )
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def stage_data(repeats: int) -> Dict[str, Any]:
    server = LocalShopServer().start()
    try:
        stats = asyncio.run(
            collect_expert_trajectories(
                server.base_url,
                str(SFT_DATA),
                repeats=repeats,
                max_steps=12,
            )
        )
    finally:
        server.stop()
    _manifest("data", stats)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return stats


def stage_sft(
    epochs: int, max_steps: int | None, model_name: str = DEFAULT_MODEL
) -> Dict[str, Any]:
    metrics = run_sft(
        str(SFT_DATA),
        str(SFT_ADAPTER),
        model_name=model_name,
        epochs=epochs,
        max_steps=max_steps,
    )
    _manifest("sft", metrics)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return metrics


def stage_rl(
    mode: str,
    epochs: int,
    group_size: int,
    max_steps: int,
    ppo_epochs: int,
    model_name: str = DEFAULT_MODEL,
) -> Dict[str, Any]:
    output = GRPO_VGDP if mode == "vgdp" else GRPO_SPARSE
    metrics = train_step_grpo(
        str(SFT_ADAPTER),
        str(output),
        model_name=model_name,
        reward_mode=mode,
        epochs=epochs,
        group_size=group_size,
        max_steps_per_episode=max_steps,
        ppo_epochs=ppo_epochs,
    )
    _manifest(f"rl_{mode}", metrics)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return metrics


def stage_eval(max_steps: int, model_name: str = DEFAULT_MODEL) -> Dict[str, Any]:
    configs = [
        {"label": "sft", "adapter": str(SFT_ADAPTER), "repair": False},
        {"label": "sft_repair", "adapter": str(SFT_ADAPTER), "repair": True},
        {
            "label": "sparse_grpo_repair",
            "adapter": str(GRPO_SPARSE),
            "repair": True,
        },
        {"label": "vgdp_grpo_repair", "adapter": str(GRPO_VGDP), "repair": True},
    ]
    report = asyncio.run(
        run_matrix(
            configs, str(OUTPUT / "eval"), model_name=model_name, max_steps=max_steps
        )
    )
    _manifest("eval", {"best": report.get("best")})
    print((OUTPUT / "eval" / "eval_report.md").read_text(encoding="utf-8"))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="AR001 real edge pipeline")
    parser.add_argument(
        "--stage",
        choices=["data", "sft", "rl_sparse", "rl_vgdp", "rl", "eval", "all"],
        default="all",
    )
    parser.add_argument("--quick", action="store_true", help="shorter run for smoke")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--sft_epochs", type=int, default=3)
    parser.add_argument("--rl_epochs", type=int, default=3)
    parser.add_argument("--group_size", type=int, default=3)
    parser.add_argument("--ppo_epochs", type=int, default=2)
    parser.add_argument("--max_steps", type=int, default=10)
    parser.add_argument("--max_sft_steps", type=int, default=0)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    if args.quick:
        args.sft_epochs = 1
        args.rl_epochs = 1
        args.group_size = 2
        args.ppo_epochs = 1
        args.max_steps = 8
        args.max_sft_steps = args.max_sft_steps or 3

    if args.stage in ("data", "all"):
        stage_data(args.repeats)
    if args.stage in ("sft", "all"):
        stage_sft(args.sft_epochs, args.max_sft_steps or None, args.model)
    if args.stage in ("rl_sparse", "rl", "all"):
        stage_rl(
            "sparse",
            args.rl_epochs,
            args.group_size,
            args.max_steps,
            args.ppo_epochs,
            args.model,
        )
    if args.stage in ("rl_vgdp", "rl", "all"):
        stage_rl(
            "vgdp",
            args.rl_epochs,
            args.group_size,
            args.max_steps,
            args.ppo_epochs,
            args.model,
        )
    if args.stage in ("eval", "all"):
        stage_eval(args.max_steps, args.model)


if __name__ == "__main__":
    main()
