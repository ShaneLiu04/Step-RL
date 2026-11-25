"""Deployment tooling: privacy gate, doctor, eval suites and the step-rl CLI."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from step_rl.cli import main
from step_rl.ops import doctor, privacy, suites

ROOT = Path(__file__).resolve().parent.parent


def _repo(tmp_path: Path, files: dict) -> Path:
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


class TestPrivacyGate:
    def test_detects_workstation_path_and_keys(self, tmp_path):
        home = "C:" + "\\Users\\" + "alice" + "\\models"
        key = "sk-" + "A" * 40
        repo = _repo(tmp_path, {"a.md": f"model at {home}\n", "b.py": f'KEY = "{key}"\n'})
        kinds = sorted(f.kind for f in privacy.scan(repo, terms=[]))
        assert kinds == ["api-key", "workstation-path"]

    def test_placeholders_and_allow_marker_are_exempt(self, tmp_path):
        repo = _repo(
            tmp_path,
            {
                "a.md": "C:" + "\\Users\\<you>\\x and /home/appuser/.local and ~/.cache\n",
                "b.py": 'FAKE = "sk-' + "B" * 40 + '"  # privacy: allow\n',
            },
        )
        assert privacy.scan(repo, terms=[]) == []

    def test_org_terms_are_reported_redacted(self, tmp_path, monkeypatch):
        term = "acme" + "corp"
        repo = _repo(tmp_path, {"notes.txt": f"built at {term.upper()} lab\n"})
        monkeypatch.setenv("STEP_RL_PRIVACY_TERMS", term)
        findings = privacy.scan(repo)
        assert [f.kind for f in findings] == ["org-term"]
        assert term not in findings[0].excerpt.lower()

    def test_credentials_in_urls(self, tmp_path):
        url = "http://" + "bob:hunter2" + "@proxy.example.org:8080"
        repo = _repo(tmp_path, {"cfg.yaml": f"proxy: {url}\n"})
        assert [f.kind for f in privacy.scan(repo, terms=[])] == ["url-credential"]

    def test_repository_is_clean(self):
        findings = privacy.scan(ROOT)
        assert findings == [], [f"{f.path}:{f.line} {f.kind}" for f in findings[:5]]


class TestDoctor:
    def test_offline_checks_report_every_area(self):
        results = doctor.run_checks(live=False, privacy=False)
        names = {c.name for c in results}
        assert {"python", "core deps", "local shop", "outputs dir", "studio auth"} <= names
        shop = next(c for c in results if c.name == "local shop")
        assert shop.status == "ok", shop.detail
        assert all(c.status in {"ok", "warn", "fail"} for c in results)

    def test_exit_code_semantics(self):
        ok = [doctor.Check("a", "ok", "")]
        warn = ok + [doctor.Check("b", "warn", "")]
        fail = warn + [doctor.Check("c", "fail", "")]
        assert doctor.exit_code(ok) == 0
        assert doctor.exit_code(warn) == 0
        assert doctor.exit_code(warn, strict=True) == 2
        assert doctor.exit_code(fail) == 1

    def test_render_json_roundtrip(self):
        import json

        out = doctor.render([doctor.Check("x", "ok", "fine")], as_json=True)
        assert json.loads(out) == [{"name": "x", "status": "ok", "detail": "fine", "hint": ""}]


class TestSuites:
    def test_suite_sizes(self):
        assert len(suites.smoke_cases()) == 6
        assert len(suites.unified_cases()) == 30

    def test_every_case_has_an_independent_target(self):
        for case in suites.smoke_cases() + suites.unified_cases():
            spec = case.expected_spec()
            assert spec.targets, case.id
            names = spec.predicate_names()
            assert names and ("cart_contains" in names or "search_done" in names), case.id

    def test_cart_to_order_requires_server_side_coupon(self):
        case = next(c for c in suites.smoke_cases() if c.id == "cart-to-order")
        names = case.expected_spec().predicate_names()
        assert "order_promo_applied" in names and "order_placed" in names

    def test_summary_and_report(self, tmp_path):
        rows = [
            {"id": "a", "group": "g", "instruction": "x", "layout": "v1", "perturb_ids": False,
             "success": True, "skill_steps": 5, "policy_steps": 0, "prompt_tokens": 0, "seconds": 1.0},
            {"id": "b", "group": "g", "instruction": "y", "layout": "v2", "perturb_ids": True,
             "success": False, "missing": ["order_placed"], "seconds": 2.0},
        ]
        summary = suites.summarize(rows, 2.5)
        assert summary["passed"] == 1 and summary["llm_steps"] == 0 and summary["wall_seconds"] == 2.5
        out = suites.write_report("unit", rows, summary, tmp_path / "r")
        assert "1/2" in (out / "report.md").read_text(encoding="utf-8")


class TestCli:
    def test_scenarios_and_version(self, capsys):
        assert main(["scenarios"]) == 0
        assert "cart-to-order" in capsys.readouterr().out
        with pytest.raises(SystemExit) as exc:
            main(["--version"])
        assert exc.value.code == 0

    def test_studio_refuses_public_bind_without_token(self, monkeypatch):
        monkeypatch.delenv("CONSOLE_TOKEN", raising=False)
        assert main(["studio", "--host", "0.0.0.0"]) == 2

    def test_run_requires_instruction(self):
        assert main(["run"]) == 2

    def test_runtime_imports_without_training_stack(self):
        code = (
            "import sys; sys.modules['torch'] = None; sys.modules['transformers'] = None;"
            "import step_rl.edge.runtime, step_rl.console.app, step_rl.cli"
        )
        proc = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
