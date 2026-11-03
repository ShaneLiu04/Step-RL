"""Response-only LoRA SFT on real expert trajectories."""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import torch
from torch.utils.data import DataLoader, Dataset

from .modeling import (
    DEFAULT_MODEL,
    get_device,
    load_tokenizer,
    lora_config,
    resolve_model_path,
    set_seed,
)
from .tasks import SFT_TASKS


def load_sft_pairs(path: str, task_ids: Optional[set] = None) -> List[Dict[str, str]]:
    pairs: List[Dict[str, str]] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            record = json.loads(line)
            if task_ids is not None and record.get("task_id") not in task_ids:
                continue
            if not record.get("success"):
                continue
            for step in record.get("steps", []):
                if step.get("exec_ok"):
                    pairs.append(
                        {"prompt": step["prompt"], "response": step["response"]}
                    )
    return pairs


class SftDataset(Dataset):
    def __init__(self, pairs: List[Dict[str, str]], tokenizer, max_length: int = 1024):
        self.pairs = pairs
        self.tokenizer = tokenizer
        self.max_length = max_length
        self.eos = tokenizer.eos_token_id

    def __len__(self) -> int:
        return len(self.pairs)

    def __getitem__(self, index: int) -> Dict[str, List[int]]:
        item = self.pairs[index]
        prompt_ids = self.tokenizer(item["prompt"], add_special_tokens=False).input_ids
        response_ids = self.tokenizer(
            item["response"], add_special_tokens=False
        ).input_ids + [self.eos]
        budget = self.max_length - len(response_ids)
        if budget <= 0:
            response_ids = response_ids[: self.max_length]
            prompt_ids = []
        elif len(prompt_ids) > budget:
            prompt_ids = prompt_ids[-budget:]
        input_ids = prompt_ids + response_ids
        labels = [-100] * len(prompt_ids) + response_ids
        return {"input_ids": input_ids, "labels": labels}


def collate(batch: List[Dict[str, List[int]]], pad_id: int) -> Dict[str, torch.Tensor]:
    max_len = max(len(item["input_ids"]) for item in batch)
    input_ids, labels, masks = [], [], []
    for item in batch:
        pad = max_len - len(item["input_ids"])
        input_ids.append(item["input_ids"] + [pad_id] * pad)
        labels.append(item["labels"] + [-100] * pad)
        masks.append([1] * len(item["input_ids"]) + [0] * pad)
    return {
        "input_ids": torch.tensor(input_ids, dtype=torch.long),
        "labels": torch.tensor(labels, dtype=torch.long),
        "attention_mask": torch.tensor(masks, dtype=torch.long),
    }


def run_sft(
    data_path: str,
    output_dir: str,
    model_name: str = DEFAULT_MODEL,
    epochs: int = 3,
    batch_size: int = 1,
    grad_accum: int = 8,
    lr: float = 2e-4,
    max_length: int = 384,
    seed: int = 42,
    max_steps: Optional[int] = None,
) -> Dict[str, Any]:
    from peft import get_peft_model
    from transformers import AutoModelForCausalLM

    set_seed(seed)
    model_path = resolve_model_path(model_name)
    tokenizer = load_tokenizer(model_path)
    pairs = load_sft_pairs(data_path, {t.task_id for t in SFT_TASKS})
    if not pairs:
        raise RuntimeError(f"no successful SFT pairs found in {data_path}")

    dtype = torch.float16 if torch.cuda.is_available() else torch.float32
    model = AutoModelForCausalLM.from_pretrained(
        model_path, dtype=dtype, low_cpu_mem_usage=True
    ).to(get_device())
    model.config.use_cache = False
    model = get_peft_model(model, lora_config())
    model.train()

    dataset = SftDataset(pairs, tokenizer, max_length=max_length)
    loader = DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=True,
        collate_fn=lambda b: collate(b, tokenizer.pad_token_id),
        drop_last=False,
    )
    optimizer = torch.optim.AdamW(
        [p for p in model.parameters() if p.requires_grad],
        lr=lr,
        weight_decay=0.0,
    )
    total_steps = max(1, math.ceil(len(loader) / grad_accum) * epochs)
    scheduler = torch.optim.lr_scheduler.LambdaLR(
        optimizer,
        lambda step: min(1.0, (step + 1) / max(1, int(total_steps * 0.05))),
    )
    scaler = torch.amp.GradScaler("cuda", enabled=torch.cuda.is_available())
    use_amp = torch.cuda.is_available()

    history: List[Dict[str, float]] = []
    global_step = 0
    started = time.time()
    optimizer.zero_grad(set_to_none=True)
    for epoch in range(epochs):
        epoch_loss = 0.0
        count = 0
        for step, batch in enumerate(loader):
            batch = {k: v.to(get_device()) for k, v in batch.items()}
            with torch.autocast(
                device_type="cuda" if use_amp else "cpu",
                dtype=torch.float16,
                enabled=use_amp,
            ):
                out = model(**batch)
                loss = out.loss / grad_accum
            scaler.scale(loss).backward()
            epoch_loss += float(out.loss.detach())
            count += 1
            if (step + 1) % grad_accum == 0 or (step + 1) == len(loader):
                scaler.unscale_(optimizer)
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                scaler.step(optimizer)
                scaler.update()
                optimizer.zero_grad(set_to_none=True)
                scheduler.step()
                global_step += 1
                if max_steps and global_step >= max_steps:
                    break
        history.append(
            {
                "epoch": epoch + 1,
                "loss": epoch_loss / max(1, count),
                "steps": global_step,
            }
        )
        if max_steps and global_step >= max_steps:
            break

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(out_dir))
    tokenizer.save_pretrained(str(out_dir))
    metrics = {
        "pairs": len(pairs),
        "epochs": epochs,
        "global_steps": global_step,
        "seconds": round(time.time() - started, 2),
        "history": history,
        "model": model_path,
        "output_dir": str(out_dir),
    }
    (out_dir / "sft_metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return metrics
