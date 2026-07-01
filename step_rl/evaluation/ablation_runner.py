"""Automated ablation study runner."""
import subprocess
import json
from pathlib import Path
from typing import Dict, List, Any
import yaml


class AblationRunner:
    """Run multiple ablation configurations and compare results."""

    def __init__(self, base_config: str = "config.yaml", output_dir: str = "./outputs/ablation"):
        self.base_config = Path(base_config)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run_ablation(self, ablation_configs: List[Dict[str, Any]]) -> Dict[str, Any]:
        results = {}
        for config in ablation_configs:
            name = config["name"]
            overrides = config.get("overrides", [])

            # Generate temporary config
            temp_config = self._generate_config(overrides)
            temp_path = self.output_dir / f"config_{name}.yaml"
            with open(temp_path, "w") as f:
                yaml.dump(temp_config, f)

            # Build benchmark command
            cmd = [
                "python", "-m", "step_rl.evaluation.benchmark",
                "--config", str(temp_path),
            ]
            if config.get("mock", False):
                cmd.append("--mock")

            result = subprocess.run(cmd, capture_output=True, text=True)

            # Parse results
            results[name] = self._parse_output(result.stdout)

        # Generate comparison report
        self._generate_report(results)
        return results

    def _generate_config(self, overrides: List[str]) -> Dict[str, Any]:
        with open(self.base_config, "r") as f:
            config = yaml.safe_load(f)

        for override in overrides:
            key, value = override.split("=", 1)
            # Simple key path traversal (e.g., "reward.progress_estimator.enabled=false")
            parts = key.split(".")
            current = config
            for part in parts[:-1]:
                current = current.setdefault(part, {})
            current[parts[-1]] = yaml.safe_load(value)

        return config

    def _parse_output(self, output: str) -> Dict[str, float]:
        """Parse benchmark output to extract metrics."""
        metrics = {}
        for line in output.split("\n"):
            if "Success Rate" in line:
                metrics["success_rate"] = float(line.split(":")[-1].strip().rstrip("%")) / 100
            elif "Avg Steps" in line:
                metrics["avg_steps"] = float(line.split(":")[-1].strip())
        return metrics

    def _generate_report(self, results: Dict[str, Any]):
        report_path = self.output_dir / "ablation_report.md"
        with open(report_path, "w") as f:
            f.write("# Ablation Study Report\n\n")
            f.write("| Configuration | Success Rate | Avg Steps |\n")
            f.write("|---|---|---|\n")
            for name, metrics in results.items():
                f.write(f"| {name} | {metrics.get('success_rate', 0):.2%} | {metrics.get('avg_steps', 0):.1f} |\n")

        print(f"Ablation report saved to {report_path}")
