"""Regression test suite using golden trajectories."""
import hashlib
import json
from pathlib import Path
from typing import Dict, List, Any
import numpy as np


class RegressionSuite:
    """Test that policy doesn't regress on known tasks."""

    def __init__(self, golden_dir: str = "./data/golden_trajectories"):
        self.golden_dir = Path(golden_dir)
        self.golden_dir.mkdir(parents=True, exist_ok=True)
        self.tasks = self._load_golden_tasks()

    def _load_golden_tasks(self) -> List[Dict[str, Any]]:
        tasks = []
        for file in self.golden_dir.glob("*.json"):
            with open(file, "r") as f:
                tasks.append(json.load(f))
        return tasks

    def register_golden_task(self, task_goal: str, expected_steps: List[str],
                              expected_success: bool = True):
        """Register a known task with expected optimal trajectory."""
        task = {
            "task_goal": task_goal,
            "expected_steps": expected_steps,
            "expected_success": expected_success,
            "min_success_rate": 0.95,
            "max_avg_steps": len(expected_steps) * 1.5,
        }
        task_id = hashlib.md5(task_goal.encode()).hexdigest()[:8]
        with open(self.golden_dir / f"task_{task_id}.json", "w") as f:
            json.dump(task, f, indent=2)
        self.tasks.append(task)

    def evaluate(self, policy_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Compare policy results against golden expectations."""
        report = {
            "total_tasks": len(self.tasks),
            "passed": 0,
            "failed": 0,
            "regressions": [],
        }

        for task in self.tasks:
            goal = task["task_goal"]
            matching_results = [r for r in policy_results if r.get("goal") == goal]

            if not matching_results:
                report["failed"] += 1
                report["regressions"].append({
                    "task": goal,
                    "reason": "No results found"
                })
                continue

            success_rate = np.mean([r["success"] for r in matching_results])
            avg_steps = np.mean([r["steps"] for r in matching_results])

            if success_rate < task["min_success_rate"]:
                report["failed"] += 1
                report["regressions"].append({
                    "task": goal,
                    "reason": f"Success rate {success_rate:.2%} < {task['min_success_rate']:.2%}"
                })
            elif avg_steps > task["max_avg_steps"]:
                report["failed"] += 1
                report["regressions"].append({
                    "task": goal,
                    "reason": f"Avg steps {avg_steps:.1f} > {task['max_avg_steps']:.1f}"
                })
            else:
                report["passed"] += 1

        return report
