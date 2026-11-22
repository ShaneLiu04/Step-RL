"""Real-run evidence writer: JSONL, screenshots, HTML, redaction (AR029)."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

_SAFE_COMPONENT = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_component(value: str) -> str:
    cleaned = _SAFE_COMPONENT.sub("_", str(value)).strip("._-")
    return (cleaned or "run")[:80]


_SECRET_KEYS = {
    "password",
    "passwd",
    "cookie",
    "cookies",
    "authorization",
    "token",
    "access_token",
    "refresh_token",
    "pt_key",
    "pt_pin",
    "thor",
    "wskey",
}
_SECRET_PATTERNS = [
    (
        re.compile(r"(?i)(password|passwd|token|cookie)\s*[=:]\s*[^\s,;]+"),
        r"\1=<redacted>",
    ),
    (
        re.compile(r"(?i)authorization:\s*bearer\s+[^\s]+"),
        "authorization: Bearer <redacted>",
    ),
]


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: ("<redacted>" if str(key).lower() in _SECRET_KEYS else redact(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        text = value
        for pattern, replacement in _SECRET_PATTERNS:
            text = pattern.sub(replacement, text)
        return text
    return value


class EvidenceWriter:
    def __init__(self, root: Path, run_id: str, site: str) -> None:
        safe_site = _safe_component(site)
        safe_run = _safe_component(run_id)
        self.root = Path(root) / safe_site / safe_run
        self.root.mkdir(parents=True, exist_ok=True)
        self.site = safe_site
        self.run_id = safe_run
        self.steps_path = self.root / "steps.jsonl"
        self.started_at = datetime.now().isoformat(timespec="seconds")

    def step(self, record: Dict[str, Any]) -> None:
        payload = {
            "run_id": self.run_id,
            "site": self.site,
            "ts": datetime.now().isoformat(timespec="seconds"),
            **redact(record),
        }
        with self.steps_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def screenshot(self, data: bytes, name: str) -> Path:
        path = self.root / f"{name}.png"
        path.write_bytes(data)
        return path

    def html(self, text: str, name: str) -> Path:
        path = self.root / f"{name}.html"
        path.write_text(redact(text), encoding="utf-8")
        return path

    def summary(self, payload: Dict[str, Any]) -> Path:
        path = self.root / "report.json"
        path.write_text(
            json.dumps(redact(payload), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path
