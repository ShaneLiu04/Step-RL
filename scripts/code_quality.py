"""Repo code-quality gate: compile, ruff F/E9, targeted tests, optional full tests."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET_TESTS = [
    "tests/test_edge_adapters.py",
    "tests/test_edge_remote_adapters.py",
    "tests/test_console.py",
    "tests/test_hybrid_system.py",
]


def run(label: str, command: list[str], cwd: Path = ROOT) -> tuple[bool, str]:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
    output = (result.stdout + result.stderr).strip()
    print(f"[{label}] rc={result.returncode}")
    if output:
        print(output[-1500:])
    return result.returncode == 0, label


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="also run full pytest")
    args = parser.parse_args()
    checks = [
        ("compileall", [sys.executable, "-m", "compileall", "-q", "step_rl", "scripts", "tests"]),
        (
            "ruff-FE9",
            [
                sys.executable,
                "-m",
                "ruff",
                "check",
                "step_rl",
                "scripts",
                "tests",
                "--select",
                "F,E9",
                "--exclude",
                "scripts/full_system_demo_video.py",
            ],
        ),
        (
            "mypy-core",
            [
                sys.executable,
                "-m",
                "mypy",
                "step_rl/logging_utils.py",
                "step_rl/edge/system.py",
                "step_rl/edge/adapters/session.py",
                "step_rl/edge/adapters/registry.py",
                "--ignore-missing-imports",
                "--follow-imports=skip",
                "--no-error-summary",
            ],
        ),
        ("targeted-tests", [sys.executable, "-m", "pytest", *TARGET_TESTS, "-q"]),
    ]
    if args.full:
        checks.append(
            (
                "full-tests",
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "tests",
                    "-q",
                    "--tb=no",
                    "--ignore=tests/test_progress_estimator.py",
                ],
            )
        )
    failed = []
    for label, command in checks:
        ok, name = run(label, command)
        if not ok:
            failed.append(name)
    print({"failed": failed, "ok": not failed})
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
