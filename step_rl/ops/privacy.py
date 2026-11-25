"""Repository privacy gate.

Generic detectors (workstation home paths, private keys, cloud/API keys,
credentials embedded in URLs) always run.  Organisation-specific terms are
never committed: they are read from ``STEP_RL_PRIVACY_TERMS`` (comma
separated) or an untracked ``.privacy-terms`` file (one term per line).

A line containing ``privacy: allow`` is exempt (used by test fixtures that
deliberately contain fake secrets).
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, List, Optional

ALLOW_MARKER = "privacy: allow"
MAX_BYTES = 2_000_000
SKIP_DIRS = {".git", "outputs", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache"}
BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".mp4", ".pdf", ".zip",
    ".gz", ".whl", ".pt", ".bin", ".safetensors", ".pkl", ".npy", ".ttf", ".woff2",
}

# Placeholders and container/CI service accounts are not personal identifiers.
_PLACEHOLDER = (
    r"(?:Public|Default|you|me|user|username|name|someone|example|runner|ubuntu|appuser|app|node|jovyan"
    r"|<[^>]*>|\.\.\.|\*|%USERNAME%|\$USER)"
)

DETECTORS = [
    ("workstation-path", re.compile(rf"\b[A-Za-z]:[\\/]{{1,2}}Users[\\/]{{1,2}}(?!{_PLACEHOLDER}(?:[\\/\s'\"`]|$))[A-Za-z0-9][\w.-]*")),
    ("home-path", re.compile(rf"/(?:home|Users)/(?!{_PLACEHOLDER}(?:[/\s'\"`]|$)|Shared/)[A-Za-z][\w.-]*/")),
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----")),
    ("api-key", re.compile(r"\b(?:sk-[A-Za-z0-9]{32,}|ghp_[A-Za-z0-9]{36}|AKIA[0-9A-Z]{16}|hf_[A-Za-z0-9]{30,}|xox[bp]-[A-Za-z0-9-]{20,})\b")),
    ("url-credential", re.compile(r"\b[a-z][a-z0-9+.-]*://[^/\s:@'\"]+:[^/\s@'\"]{3,}@[\w.-]+")),
]


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    kind: str
    excerpt: str

    def to_dict(self) -> dict:
        return asdict(self)


def load_terms(root: Path) -> List[str]:
    terms = [t.strip() for t in os.environ.get("STEP_RL_PRIVACY_TERMS", "").split(",")]
    local = root / ".privacy-terms"
    if local.is_file():
        for raw in local.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if raw and not raw.startswith("#"):
                terms.append(raw)
    return sorted({t for t in terms if t})


def _candidate_files(root: Path) -> Iterable[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=root, capture_output=True, check=True,
        ).stdout.decode("utf-8", "replace")
        names = [n for n in out.split("\0") if n]
        for name in names:
            yield root / name
        return
    except (OSError, subprocess.CalledProcessError):
        pass
    for path in root.rglob("*"):
        if path.is_file() and not (set(path.relative_to(root).parts) & SKIP_DIRS):
            yield path


def _redact(text: str, start: int, end: int) -> str:
    snippet = text[max(0, start - 24): end + 24].strip()
    return snippet[:120]


def scan(root: Path, terms: Optional[List[str]] = None) -> List[Finding]:
    root = root.resolve()
    terms = load_terms(root) if terms is None else terms
    term_rx = re.compile("|".join(re.escape(t) for t in terms), re.IGNORECASE) if terms else None
    findings: List[Finding] = []
    for path in _candidate_files(root):
        rel = path.relative_to(root).as_posix()
        if path.name == ".privacy-terms" or path.suffix.lower() in BINARY_SUFFIXES:
            continue
        if set(Path(rel).parts) & SKIP_DIRS:
            continue
        try:
            if not path.is_file() or path.stat().st_size > MAX_BYTES:
                continue
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if ALLOW_MARKER in line:
                continue
            for kind, rx in DETECTORS:
                for m in rx.finditer(line):
                    findings.append(Finding(rel, lineno, kind, _redact(line, m.start(), m.end())))
            if term_rx is not None:
                hits = len(term_rx.findall(line))
                findings.extend(Finding(rel, lineno, "org-term", "<redacted term>") for _ in range(hits))
    return findings
