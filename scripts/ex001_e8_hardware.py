"""E8: CPU planner/verifier/server latency + GPU generation latency/memory."""

from __future__ import annotations

import json
import statistics
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import torch  # noqa: E402

from step_rl.edge.modeling import (  # noqa: E402
    load_policy,
    resolve_model_path,
)
from step_rl.edge.planner import CatalogItem, plan_instruction  # noqa: E402
from step_rl.edge.site import LocalShopServer  # noqa: E402
from step_rl.edge.tasks import TASK_BY_ID  # noqa: E402
from step_rl.edge.verifier import compute_progress  # noqa: E402

OUT = ROOT / "outputs" / "ex001"


def pct(values, q):
    values = sorted(values)
    index = min(len(values) - 1, int(len(values) * q))
    return values[index]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    catalog = [
        CatalogItem("p1", "iPhone 15 智能手机", 6999, 9, ("iphone", "手机", "apple")),
        CatalogItem("p2", "USB-C 快充数据线", 59, 9, ("usb", "数据线", "cable", "充电")),
        CatalogItem("p3", "无线充电器", 199, 9, ("无线", "充电器", "charger")),
        CatalogItem("p4", "蓝牙降噪耳机", 399, 5, ("蓝牙", "耳机", "headphone")),
    ]
    instruction = "预算650元，买无线充电器和蓝牙耳机各一件，并结算"
    planner_times = []
    for _ in range(1000):
        start = time.perf_counter()
        plan_instruction(instruction, catalog)
        planner_times.append((time.perf_counter() - start) * 1000)

    task = TASK_BY_ID["ev_checkout_p3"]
    state = {
        "query": "无线",
        "cart": {"p3": 2},
        "form": {"name": "A", "address": "B"},
        "order": None,
        "visited": ["/search?q=无线", "/product/p3", "/cart", "/checkout"],
    }
    verifier_times = []
    for _ in range(1000):
        start = time.perf_counter()
        compute_progress(state, "/checkout", task)
        verifier_times.append((time.perf_counter() - start) * 1000)

    server = LocalShopServer().start()
    http_times = []
    try:
        for _ in range(200):
            start = time.perf_counter()
            urllib.request.urlopen(server.base_url + "/api/products").read()
            http_times.append((time.perf_counter() - start) * 1000)
    finally:
        server.stop()

    gpu_result = {}
    if torch.cuda.is_available():
        from step_rl.edge.rollout import generate_action

        model, tokenizer = load_policy(
            resolve_model_path(), "outputs/ar004/sft_semantic"
        )
        prompt = (
            "任务: 搜索无线充电器并加入购物车\n页面: / | 首页\n"
            "可交互元素:\n- e1 role=textbox name=搜索商品\n"
            "- e2 role=button name=搜索\n"
        )
        torch.cuda.reset_peak_memory_stats()
        gen_times = []
        tokens = 0
        for _ in range(20):
            start = time.perf_counter()
            out = generate_action(
                model, tokenizer, prompt, sample=False, max_new_tokens=48
            )
            gen_times.append((time.perf_counter() - start) * 1000)
            tokens += len(out["response_ids"])
        gpu_result = {
            "gpu": torch.cuda.get_device_name(0),
            "gen_p50_ms": pct(gen_times, 0.5),
            "gen_p95_ms": pct(gen_times, 0.95),
            "peak_memory_mb": round(torch.cuda.max_memory_allocated() / 1e6, 1),
            "avg_generated_tokens": tokens / 20,
            "tokens_per_second": round(tokens / (sum(gen_times) / 1000), 2),
        }

    result = {
        "cpu": {
            "planner_p50_ms": pct(planner_times, 0.5),
            "planner_p95_ms": pct(planner_times, 0.95),
            "verifier_p50_ms": pct(verifier_times, 0.5),
            "verifier_p95_ms": pct(verifier_times, 0.95),
            "http_p50_ms": pct(http_times, 0.5),
            "http_p95_ms": pct(http_times, 0.95),
        },
        "gpu": gpu_result,
        "clock_note": "local GPU is clock-capped; see nvidia-smi in report",
    }
    (OUT / "e8_hardware.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
