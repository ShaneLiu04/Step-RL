"""
Quick-start pipeline for Step-RL v2.0
Runs the full training pipeline with demo data.
Usage:
  python scripts/run_pipeline.py --stage all      # Run everything
  python scripts/run_pipeline.py --stage sft      # SFT only
  python scripts/run_pipeline.py --stage reward   # Progress Estimator only
  python scripts/run_pipeline.py --stage grpo     # GRPO only
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path


def run_cmd(cmd: list, desc: str):
    print(f"\n{'='*60}")
    print(f"Running: {desc}")
    print(f"Command: {' '.join(cmd)}")
    print(f"{'='*60}\n")
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        print(f"[WARNING] {desc} exited with code {result.returncode}")
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="Step-RL v2.0 Quick Pipeline")
    parser.add_argument("--stage", type=str, default="all",
                        choices=["all", "data", "sft", "reward", "grpo", "test"])
    parser.add_argument("--base_model", type=str, default="Qwen/Qwen3-8B-Instruct")
    parser.add_argument("--mock_model", action="store_true",
                        help="Use GPT-2 for fast integration testing instead of Qwen")
    parser.add_argument("--use_4bit", action="store_true", help="Enable 4-bit quantization")
    args = parser.parse_args()

    project_root = Path(__file__).parent.parent
    os.chdir(project_root)

    # Check GPU
    import torch
    if torch.cuda.is_available():
        mem_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
        print(f"GPU: {torch.cuda.get_device_name(0)} | VRAM: {mem_gb:.1f} GB")
        if mem_gb < 12 and not args.use_4bit and not args.mock_model:
            print("\n[!] Your GPU has < 12GB VRAM. Auto-enabling --mock_model for safety.")
            print("    To run with real Qwen models, use --use_4bit flag.")
            args.mock_model = True
    else:
        print("No GPU detected. Training will be very slow.")

    success = True

    # Stage 0: Prepare data
    if args.stage in ("all", "data"):
        success &= run_cmd([sys.executable, "scripts/prepare_mock_data.py"], "Prepare Mock Data")

    # Stage 1: SFT Warmup
    if args.stage in ("all", "sft"):
        model = "gpt2" if args.mock_model else args.base_model
        if args.mock_model:
            # Use simplified SFT for GPT-2 validation (avoids Trainer compat issues)
            cmd = [
                sys.executable, "scripts/sft_simple.py",
                "--data_dir", "./data/sft",
                "--output_dir", "./outputs/sft_warmup",
                "--base_model", model,
                "--epochs", "1",
                "--batch_size", "2",
            ]
        else:
            cmd = [
                sys.executable, "-m", "step_rl.training.sft_warmup",
                "--config", "config.yaml",
                "--data_dir", "./data/sft",
                "--output_dir", "./outputs/sft_warmup",
                "--base_model", model,
                "--num_epochs", "1",
                "--batch_size", "2",
            ]
            if args.use_4bit:
                cmd.append("--use_4bit")
        success &= run_cmd(cmd, "SFT Warmup")

    # Stage 2: Progress Estimator
    if args.stage in ("all", "reward"):
        model = "gpt2" if args.mock_model else args.base_model
        cmd = [
            sys.executable, "-m", "step_rl.reward.train_reward_model",
            "--config", "config.yaml",
            "--data_path", "./data/progress/demo_labels.json",
            "--output_dir", "./checkpoints/progress_estimator",
            "--base_model", model,
            "--epochs", "2",
            "--batch_size", "4",
        ]
        success &= run_cmd(cmd, "Train Progress Estimator")

    # Stage 3: GRPO Training
    if args.stage in ("all", "grpo"):
        sft_path = "./outputs/sft_warmup/sft_adapter"
        progress_path = "./checkpoints/progress_estimator/best_model.pt"

        if not Path(sft_path).exists():
            print(f"[ERROR] SFT adapter not found at {sft_path}. Run --stage sft first.")
            return

        cmd = [
            sys.executable, "-m", "step_rl.training.grpo_trainer",
            "--config", "config.yaml",
            "--sft_adapter", sft_path,
            "--output_dir", "./checkpoints/grpo",
        ]
        if Path(progress_path).exists():
            cmd.extend(["--progress_model", progress_path])
        success &= run_cmd(cmd, "GRPO Training")

    # Stage 4: End-to-end integration test
    if args.stage in ("all", "test"):
        success &= run_cmd([sys.executable, "scripts/end_to_end_test.py"], "End-to-End Integration Test")

    print(f"\n{'='*60}")
    if success:
        print("Pipeline completed successfully!")
    else:
        print("Pipeline completed with some warnings/errors. Check logs above.")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
