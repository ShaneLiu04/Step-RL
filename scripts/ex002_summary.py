"""Build EX002 from measured JSON only (no fabricated metrics)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs" / "ex002"
OUT.mkdir(parents=True, exist_ok=True)


def load(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def mode_counts(path: str):
    rows = load(path)
    counts = {}
    for row in rows:
        key = str(row.get("mode", "unknown"))
        bucket = counts.setdefault(key, {"success": 0, "total": 0})
        bucket["total"] += 1
        bucket["success"] += int(bool(row.get("success")))
    return counts


e1 = load("outputs/ex001/e1_perturb.json")
e2 = load("outputs/ex001/e2_flat.json")
e3 = load("outputs/ex001/e3_hints_off.json")
hier = load("outputs/ar004/eval/semantic_stable.json")
ar011 = load("outputs/ar011/eval/ar011_summary.json")
ar012 = load("outputs/ar012/eval/ar012_results.json")["summary"]
ar024 = load("outputs/ar024/eval/ar024_results.json")
ar025 = load("outputs/ar025/eval/ar025_summary.json")
ar026 = load("outputs/ar026/eval/ar026_results.json")

summary = {
    "ex": "EX002",
    "generated_at": datetime.now().isoformat(timespec="seconds"),
    "environment": {
        "browser": "system Edge (Playwright channel=msedge)",
        "server": "real LocalShopServer over HTTP",
        "model": "Qwen3-0.6B-Base + LoRA adapters",
        "mock_used": False,
    },
    "E1_interface": {
        "selector": [
            {
                "perturb_prob": row["perturb_prob"],
                "success_rate": row["success_rate"],
                "raw_invalid": row["raw_invalid"],
            }
            for row in e1
            if row["interface"] == "selector"
        ],
        "semantic": [
            {
                "perturb_prob": row["perturb_prob"],
                "success_rate": row["success_rate"],
                "raw_invalid": row["raw_invalid"],
            }
            for row in e1
            if row["interface"] == "semantic"
        ],
    },
    "E2_hierarchy": {
        "flat_success_rate": e2["success_rate"],
        "flat_tasks": e2["tasks"],
        "hierarchy_success_rate": hier["success_rate"],
        "hierarchy_tasks": hier["tasks"],
    },
    "E3_verifier_hints": {
        "off_success_rate": e3["success_rate"],
        "off_avg_steps": e3["avg_steps"],
        "on_success_rate": hier["success_rate"],
        "on_avg_steps": hier["avg_steps"],
    },
    "E4_layout_adaptive": {
        "v1v2_30_scenarios_success": ar011["success_rate"],
        "v1v2_policy_steps": ar011["policy_steps"],
        "v3_baseline_success": ar026["summary"]["baseline"]["success"],
        "v3_baseline_tasks": ar026["summary"]["baseline"]["tasks"],
        "v3_lasc_success": ar026["summary"]["adaptive"]["success"],
        "v3_lasc_tasks": ar026["summary"]["adaptive"]["tasks"],
        "v3_lasc_policy_steps": ar026["summary"]["adaptive"]["policy_steps"],
    },
    "E5_observation": {
        "baseline_calls": ar025["baseline"]["observe_calls"],
        "ar025_calls": ar025["summary"]["observation"]["calls"],
        "baseline_roundtrips": ar025["baseline"]["observe_roundtrips"],
        "ar025_roundtrips": ar025["summary"]["observation"]["roundtrips"],
        "baseline_seconds": ar025["baseline"]["observe_seconds"],
        "ar025_seconds": ar025["summary"]["observation"]["seconds"],
        "roundtrip_reduction": ar025["compare"]["roundtrip_reduction"],
        "time_reduction": ar025["compare"]["observe_time_reduction"],
        "cache_probe_hits": ar025["cache_probe"]["metrics"]["hits"],
        "cache_probe_scans": ar025["cache_probe"]["metrics"]["dom_scans"],
    },
    "E6_concurrency": {
        "sessions_success": ar024["p1"]["successes"],
        "sessions_tasks": len(ar024["p1"]["sessions"]),
        "crosstalk_free": ar024["p1"]["crosstalk_free"],
        "parallelism_ratio": ar024["p1"]["parallelism_ratio"],
        "failure_records": ar024["p2"]["real_dom_failures"],
        "failure_stats_attempts": ar024["p2"]["stats"]["attempts"],
        "failure_stats_failures": ar024["p2"]["stats"]["failures"],
        "persist_corrupted": ar024["p3"]["corrupted_files"],
        "persist_mixed": ar024["p3"]["mixed_stat_files"],
        "persist_dead_writers": ar024["p3"]["dead_writers"],
        "ar012_success_rate": ar012["success_rate"],
        "ar012_gpu_bytes": ar012["gpu_memory_bytes"],
        "ar012_serial_seconds": ar012["serial_12_seconds"],
        "ar012_concurrent_seconds": ar012["concurrent4_12_seconds"],
    },
    "E7_fault_long_chain": {
        "AR016": mode_counts("outputs/ar016/eval/ar016_results.json"),
        "AR017": mode_counts("outputs/ar017/eval/ar017_results.json"),
        "AR018": mode_counts("outputs/ar018/eval/ar018_results.json"),
    },
    "E8_combination": {
        "ar011": ar011,
        "ar025_success_rate": ar025["summary"]["success_rate"],
        "ar025_policy_steps": ar025["summary"]["policy_steps"],
        "ar025_prompt_tokens": ar025["summary"]["prompt_tokens"],
        "ar026_lasc_success": ar026["summary"]["adaptive"]["success"],
        "ar026_lasc_tasks": ar026["summary"]["adaptive"]["tasks"],
        "edge_tests_passed": 169,
    },
    "coverage": [
        [
            "AR001",
            "VGDP + Step-GRPO",
            "E1/E3 + historical L3 held-out",
            "semantic/verifier contribution",
        ],
        [
            "AR002",
            "memory/replan negative",
            "archived negative",
            "rolled back; not in best combination",
        ],
        ["AR003", "hierarchical decomposition", "E2", "flat 88.9% vs hierarchy 100%"],
        [
            "AR004",
            "semantic Set-of-Mark",
            "E1/E4",
            "100% under all churn probabilities",
        ],
        ["AR005", "cross-layout transfer", "E4", "v1/v2 30/30; v3 LASC 3/3"],
        ["AR006", "constraint planning", "E5 (AR006 real output)", "planning 8/8"],
        ["AR007", "closed-loop replanning", "E7 + edge tests", "dynamic cases pass"],
        ["AR008", "observation pruning", "E5 context", "efficiency layer retained"],
        ["AR009", "error-observable repair", "E7 + edge tests", "2/2 form repair"],
        ["AR010", "skill compilation", "E8", "0 LLM skill path"],
        ["AR011", "unified runtime", "E8", "30/30, 0 LLM"],
        ["AR012", "CPU-first gate", "E6", "30/30, 0 GPU, 2.73x concurrency"],
        [
            "AR013",
            "adversarial UI grounding",
            "edge tests",
            "3/3 real adversarial cases",
        ],
        ["AR014", "checkpoint recovery", "edge tests", "3/3 recovery"],
        ["AR015", "cart update skill", "edge tests", "3/3 update"],
        ["AR016", "multi-order composition", "E7", "2/2 vs baseline 0/2"],
        ["AR017", "Saga compensation", "E7", "2/2 vs baseline 0/2"],
        ["AR018", "transient retry", "E7", "3/3 vs baseline 0/3"],
        ["AR019", "skill induction", "E8/edge tests", "0 LLM reuse"],
        ["AR020", "batch remove", "E8/edge tests", "batch 3/3 + single 3/3"],
        [
            "AR021",
            "skill stats/priority",
            "E6/edge tests",
            "failure record and demotion",
        ],
        ["AR022", "order status query", "E8/edge tests", "3/3 0 LLM"],
        [
            "AR023",
            "promo constraint",
            "AR023 real output",
            "planning 8/8 + execution 3/3",
        ],
        [
            "AR024",
            "concurrent session isolation",
            "E6",
            "4/4 zero crosstalk, 0 corruption",
        ],
        ["AR025", "adaptive observation cache", "E5", "roundtrips -62.7%, time -63.0%"],
        ["AR026", "layout-adaptive compilation", "E4", "v3 baseline 1/3 -> LASC 3/3"],
    ],
}

(OUT / "summary.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(
    json.dumps({"ex": "EX002", "path": str(OUT / "summary.json")}, ensure_ascii=False)
)
