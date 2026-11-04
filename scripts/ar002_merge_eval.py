"""Merge VGDP and Sparse LoRA adapters, then evaluate the real held-out matrix.

This is a model-soup experiment: both adapters share the same SFT base, so a
weighted merge can combine skills without a task router.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import torch  # noqa: E402
from peft import PeftModel  # noqa: E402

from step_rl.edge.evaluate import evaluate_policy  # noqa: E402
from step_rl.edge.modeling import (  # noqa: E402
    load_base_model,
    load_tokenizer,
    resolve_model_path,
)
from step_rl.edge.tasks import EVAL_TASKS  # noqa: E402

SFT = "outputs/ar001/sft_adapter"
VGDP = "outputs/ar001/grpo_vgdp"
SPARSE = "outputs/ar001/grpo_sparse"
OUT = ROOT / "outputs" / "ar002"
MERGED = OUT / "merged_adapter"


def build_merged(weight_vgdp: float = 0.5) -> None:
    model_path = resolve_model_path()
    tokenizer = load_tokenizer(model_path)
    base = load_base_model(model_path)
    model = PeftModel.from_pretrained(base, SFT, adapter_name="sft")
    model.load_adapter(VGDP, adapter_name="vgdp")
    model.load_adapter(SPARSE, adapter_name="sparse")
    model.add_weighted_adapter(
        ["vgdp", "sparse"],
        [weight_vgdp, 1.0 - weight_vgdp],
        "merged",
        combination_type="linear",
    )
    model.set_adapter("merged")
    MERGED.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(MERGED), selected_adapters=["merged"])
    tokenizer.save_pretrained(str(MERGED))
    (MERGED / "merge_config.json").write_text(
        json.dumps({"vgdp": weight_vgdp, "sparse": 1 - weight_vgdp}, indent=2),
        encoding="utf-8",
    )
    del model, base
    torch.cuda.empty_cache()


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    weight = float(sys.argv[1]) if len(sys.argv) > 1 else 0.5
    build_merged(weight)
    summary = asyncio.run(
        evaluate_policy(
            f"merged_vgdp{weight:.1f}",
            str(MERGED / "merged"),
            repair=True,
            tasks=EVAL_TASKS,
            max_steps=8,
        )
    )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"merged_{weight:.2f}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {k: v for k, v in summary.items() if k != "results"},
            ensure_ascii=False,
            indent=2,
        )
    )
    for item in summary["results"]:
        print(item["task_id"], item["success"], round(item["final_progress"], 2))


if __name__ == "__main__":
    main()
