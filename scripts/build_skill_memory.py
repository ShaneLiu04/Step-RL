"""Build a compact skill memory from real successful expert trajectories."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from step_rl.edge.skill_memory import (  # noqa: E402
    MemoryRecord,
    SkillMemory,
    compact_action,
    page_type,
    target_pid_of,
)
from step_rl.edge.tasks import SFT_TASKS, TASK_BY_ID, TRAIN_RL_TASKS  # noqa: E402

ALLOWED = {t.task_id for t in SFT_TASKS + TRAIN_RL_TASKS}


def build(source: str) -> SkillMemory:
    best = {}
    with open(source, "r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            record = json.loads(line)
            if not record.get("success") or record.get("task_id") not in ALLOWED:
                continue
            task = TASK_BY_ID[record["task_id"]]
            for step in record.get("steps", []):
                if not step.get("exec_ok"):
                    continue
                delta = float(step.get("phi_after", 0.0)) - float(
                    step.get("phi_before", 0.0)
                )
                if delta < 0:
                    continue
                action = compact_action(step["action"])
                key = (
                    page_type(step.get("page", "/")),
                    tuple(sorted(step.get("missing", []))),
                    json.dumps(action, ensure_ascii=False, sort_keys=True),
                    target_pid_of(action),
                )
                candidate = MemoryRecord(
                    level=task.level,
                    require_checkout=task.require_checkout,
                    page_type=page_type(step.get("page", "/")),
                    missing=list(step.get("missing", [])),
                    action=action,
                    delta_phi=delta,
                    target_pid=target_pid_of(action),
                )
                if key not in best or candidate.delta_phi > best[key].delta_phi:
                    best[key] = candidate
    return SkillMemory(sorted(best.values(), key=lambda r: (r.level, r.page_type)))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="outputs/ar002/expert_train.jsonl")
    parser.add_argument("--out", default="step_rl/edge/skill_memory.json")
    args = parser.parse_args()
    memory = build(args.source)
    memory.save(args.out)
    size = Path(args.out).stat().st_size
    print(f"[OK] records={len(memory.records)} size={size} bytes -> {args.out}")
    if size > 20000:
        print("[WARN] memory exceeds 20KB; consider pruning")


if __name__ == "__main__":
    main()
