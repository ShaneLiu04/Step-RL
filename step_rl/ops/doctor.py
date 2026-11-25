"""``step-rl doctor``: deployment readiness checks for a target machine.

Each check returns ``ok`` / ``warn`` / ``fail``.  ``fail`` means the
deterministic runtime or Studio cannot run; ``warn`` marks optional
capabilities (training stack, GPU) or security posture to review.
"""

from __future__ import annotations

import importlib
import json
import os
import platform
import shutil
import sys
import tempfile
import time
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, List, Optional

ROOT = Path(__file__).resolve().parent.parent.parent

_BROWSER_PATHS = {
    "msedge": [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/usr/bin/microsoft-edge",
        "/usr/bin/microsoft-edge-stable",
    ],
    "chrome": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
    ],
}


@dataclass
class Check:
    name: str
    status: str
    detail: str
    hint: str = ""


def _module(name: str) -> tuple[bool, str]:
    try:
        mod = importlib.import_module(name)
        return True, str(getattr(mod, "__version__", "") or "installed")
    except Exception as exc:  # broken installs raise ImportError subclasses or worse
        return False, f"{type(exc).__name__}: {str(exc).splitlines()[0][:110]}"


def check_python() -> Check:
    ok = sys.version_info >= (3, 10)
    return Check("python", "ok" if ok else "fail", platform.python_version(), "" if ok else "Python 3.10+ required")


def check_core() -> Check:
    missing = [n for n in ("fastapi", "uvicorn", "pydantic", "yaml") if not _module(n)[0]]
    if missing:
        return Check("core deps", "fail", "missing: " + ", ".join(missing), 'pip install -e ".[studio]"')
    return Check("core deps", "ok", "fastapi · uvicorn · pydantic · pyyaml")


def check_playwright() -> Check:
    ok, detail = _module("playwright")
    if not ok:
        return Check("playwright", "fail", detail, 'pip install -e ".[studio]"')
    return Check("playwright", "ok", "python bindings installed")


def browser_executable() -> tuple[str, str]:
    override = os.environ.get("STEP_RL_BROWSER_PATH", "")
    if override:
        return ("STEP_RL_BROWSER_PATH", override if Path(override).is_file() else "")
    channel = os.environ.get("STEP_RL_BROWSER_CHANNEL", "msedge")
    for path in _BROWSER_PATHS.get(channel, []):
        if Path(path).is_file():
            return channel, path
    found = shutil.which("msedge" if channel == "msedge" else "google-chrome")
    return channel, found or ""


def check_browser() -> Check:
    source, path = browser_executable()
    if path:
        return Check("browser", "ok", f"{source}: {Path(path).name}")
    bundled = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", Path.home() / ".cache" / "ms-playwright"))
    if sys.platform == "win32":
        bundled = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    if any(bundled.glob("chromium-*")):
        return Check("browser", "warn", "system channel missing; bundled Chromium present",
                     "set STEP_RL_BROWSER_CHANNEL=chromium")
    return Check("browser", "fail", f"no executable for channel '{source}'",
                 "install Edge/Chrome, or `playwright install chromium`, or set STEP_RL_BROWSER_PATH")


def check_shop() -> Check:
    from ..edge.site import PRODUCTS, LocalShopServer

    server = LocalShopServer().start()
    try:
        t0 = time.perf_counter()
        with urllib.request.urlopen(f"{server.base_url}/api/products", timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        ms = (time.perf_counter() - t0) * 1000
        count = len(body) if isinstance(body, list) else len(body.get("products", []))
        status = "ok" if count == len(PRODUCTS) else "warn"
        return Check("local shop", status, f"{count} products served in {ms:.0f} ms")
    except Exception as exc:
        return Check("local shop", "fail", f"{type(exc).__name__}: {exc}")
    finally:
        server.stop()


def check_live_browser() -> Check:
    import asyncio

    from ..edge.browser import BrowserEnv
    from ..edge.site import LocalShopServer
    from ..edge.tasks import TaskSpec

    async def probe() -> str:
        server = LocalShopServer().start()
        channel = os.environ.get("STEP_RL_BROWSER_CHANNEL", "msedge")
        env = BrowserEnv(server, channel=None if channel == "chromium" else channel, headless=True, semantic=True)
        try:
            t0 = time.perf_counter()
            obs = await env.reset(TaskSpec("doctor", 1, "probe", "", {}))
            elements = len(obs.get("elements", [])) if isinstance(obs, dict) else 0
            return f"page rendered, {elements} interactive elements, {(time.perf_counter() - t0):.1f}s"
        finally:
            await env.close()
            server.stop()

    try:
        return Check("live browser", "ok", asyncio.run(probe()))
    except Exception as exc:
        return Check("live browser", "fail", f"{type(exc).__name__}: {str(exc).splitlines()[0][:120]}",
                     "run without --live to isolate; check browser channel and sandbox permissions")


def check_training() -> Check:
    torch_ok, torch_detail = _module("torch")
    tf_ok, tf_detail = _module("transformers")
    if torch_ok and tf_ok:
        return Check("training stack", "ok", f"torch {torch_detail} · transformers {tf_detail}")
    def short(detail: str) -> str:
        return detail if len(detail) <= 60 else detail[:59] + "…"

    broken = []
    if not torch_ok:
        broken.append(f"torch ({short(torch_detail)})")
    if not tf_ok:
        broken.append(f"transformers ({short(tf_detail)})")
    return Check("training stack", "warn", "; ".join(broken),
                 'optional: pip install -e ".[train]" (runtime needs none of it)')


def check_gpu() -> Check:
    try:
        import torch

        if torch.cuda.is_available():
            return Check("gpu", "ok", torch.cuda.get_device_name(0))
        return Check("gpu", "warn", "no CUDA device — CPU-first runtime is fully supported")
    except Exception:
        return Check("gpu", "warn", "torch unavailable — skipped")


def check_outputs() -> Check:
    target = ROOT / "outputs"
    try:
        target.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target, delete=True):
            pass
        return Check("outputs dir", "ok", "writable")
    except OSError as exc:
        return Check("outputs dir", "fail", str(exc), "set a writable working directory")


def check_skills() -> Check:
    path = ROOT / "step_rl" / "edge" / "skill_memory.json"
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
        return Check("skill memory", "ok", f"{len(records)} records")
    except (OSError, ValueError) as exc:
        return Check("skill memory", "warn", f"{type(exc).__name__}", "rebuild with scripts/build_skill_memory.py")


def check_security() -> Check:
    if os.environ.get("CONSOLE_TOKEN"):
        return Check("studio auth", "ok", "CONSOLE_TOKEN set")
    return Check("studio auth", "warn", "no CONSOLE_TOKEN — Studio must stay on 127.0.0.1",
                 "export CONSOLE_TOKEN before binding a non-loopback host")


def check_privacy() -> Check:
    from .privacy import scan

    findings = scan(ROOT)
    if findings:
        first = findings[0]
        return Check("privacy gate", "fail", f"{len(findings)} findings, e.g. {first.path}:{first.line} ({first.kind})",
                     "run `step-rl privacy-scan` for the full list")
    return Check("privacy gate", "ok", "0 findings")


def run_checks(live: bool = False, privacy: bool = True) -> List[Check]:
    checks: List[Callable[[], Check]] = [
        check_python, check_core, check_playwright, check_browser, check_shop,
        check_outputs, check_skills, check_security, check_training, check_gpu,
    ]
    if privacy:
        checks.append(check_privacy)
    if live:
        checks.append(check_live_browser)
    results = []
    for fn in checks:
        try:
            results.append(fn())
        except Exception as exc:
            results.append(Check(fn.__name__.removeprefix("check_"), "fail", f"{type(exc).__name__}: {exc}"))
    return results


def render(results: List[Check], as_json: bool = False) -> str:
    if as_json:
        return json.dumps([asdict(c) for c in results], ensure_ascii=False, indent=2)
    icon = {"ok": "✓", "warn": "!", "fail": "✗"}
    width = max(len(c.name) for c in results)
    lines = []
    for c in results:
        line = f" {icon[c.status]}  {c.name.ljust(width)}  {c.detail}"
        if c.hint and c.status != "ok":
            line += f"\n    {' ' * width}  → {c.hint}"
        lines.append(line)
    fails = sum(c.status == "fail" for c in results)
    warns = sum(c.status == "warn" for c in results)
    verdict = "READY" if not fails else "NOT READY"
    lines.append(f"\n {verdict} · {len(results) - fails - warns} ok · {warns} warn · {fails} fail")
    return "\n".join(lines)


def exit_code(results: List[Check], strict: Optional[bool] = False) -> int:
    if any(c.status == "fail" for c in results):
        return 1
    if strict and any(c.status == "warn" for c in results):
        return 2
    return 0
