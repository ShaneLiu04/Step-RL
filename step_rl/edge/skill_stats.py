"""Skill outcome statistics, priority ranking and demotion (AR021).

AR019/AR020 turned successful LLM-fallback trajectories into reusable
parameterised skills, but the registry kept no memory of how those skills
perform afterwards: a stale template (e.g. from an older site generation)
was re-selected on every run and failed the same way, while the
capability gate kept reporting ``covered``.

This module records the **verifier-confirmed** success/failure of every
skill execution (the only legal success signal in this project), ranks
candidates for the same operation by real success rate and demotes a
skill once its observed rate proves it worse than a coin flip.  Demotion
removes a skill from the selection set only - it is kept in the registry
and in the audit file, so the decision stays traceable.  A fresh
trajectory re-registered under the same name resets its statistics
(self-healing closed loop, AR019 semantics).

No edge-internal imports: pure data + policy, so it can never create an
import cycle.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

# Demotion policy (design.md D2): after at least ``DEMOTION_MIN_ATTEMPTS``
# attempts, a skill is demoted when its success rate is *strictly below*
# ``DEMOTION_MAX_RATE``.  1/2 (= 0.5) is kept; 0/1, 1/3, 0/2 are demoted.
DEMOTION_MIN_ATTEMPTS = 1
DEMOTION_MAX_RATE = 0.5


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class SkillStat:
    """Per-skill execution statistics (verifier-confirmed outcomes only)."""

    name: str
    operation: str
    attempts: int = 0
    successes: int = 0
    failures: int = 0
    consecutive_failures: int = 0
    last_success_at: str = ""
    last_failure_at: str = ""
    last_failure_note: str = ""
    demoted: bool = False
    demotion_reason: str = ""

    @property
    def success_rate(self) -> float:
        return self.successes / self.attempts if self.attempts else 0.0


def _apply_demotion_policy(stat: SkillStat) -> None:
    """Set ``demoted`` when the observed rate proves the skill bad.

    Demotion is sticky: later successes never clear it on their own.
    Recovery happens only through a same-name re-registration (fresh
    trajectory, statistics reset) or an explicit ``reset_skill_stats``.
    """

    if stat.demoted:
        return
    if stat.attempts >= DEMOTION_MIN_ATTEMPTS and stat.success_rate < DEMOTION_MAX_RATE:
        stat.demoted = True
        stat.demotion_reason = (
            f"success_rate {stat.success_rate:.2f} < {DEMOTION_MAX_RATE:.2f} "
            f"after {stat.attempts} attempt(s)"
        )


_STATS: Dict[str, SkillStat] = {}


def record_skill_outcome(
    name: str,
    operation: str,
    success: bool,
    note: str = "",
) -> SkillStat:
    """Record one verifier-confirmed outcome for skill ``name``."""

    stat = _STATS.get(name)
    if stat is None:
        stat = SkillStat(name=name, operation=operation)
        _STATS[name] = stat
    stat.attempts += 1
    if success:
        stat.successes += 1
        stat.consecutive_failures = 0
        stat.last_success_at = _now()
    else:
        stat.failures += 1
        stat.consecutive_failures += 1
        stat.last_failure_at = _now()
        if note:
            stat.last_failure_note = note
    _apply_demotion_policy(stat)
    return stat


def get_skill_stat(name: str) -> Optional[SkillStat]:
    return _STATS.get(name)


def all_skill_stats() -> Dict[str, SkillStat]:
    return dict(_STATS)


def is_demoted(name: str) -> bool:
    stat = _STATS.get(name)
    return bool(stat is not None and stat.demoted)


def reset_skill_stats(name: str) -> None:
    """Drop all statistics for ``name`` (same-name re-registration)."""

    _STATS.pop(name, None)


def clear_skill_stats() -> None:
    _STATS.clear()


def _policy() -> Dict[str, float]:
    return {
        "min_attempts": DEMOTION_MIN_ATTEMPTS,
        "max_rate": DEMOTION_MAX_RATE,
    }


def to_dict() -> Dict[str, Any]:
    return {
        "policy": _policy(),
        "skills": {name: asdict(stat) for name, stat in _STATS.items()},
    }


def from_dict(data: Dict[str, Any]) -> None:
    """Restore statistics from an audit file (replaces current memory)."""

    _STATS.clear()
    for name, raw in (data.get("skills") or {}).items():
        stat = SkillStat(
            name=str(raw.get("name", name)),
            operation=str(raw.get("operation", "")),
            attempts=int(raw.get("attempts", 0)),
            successes=int(raw.get("successes", 0)),
            failures=int(raw.get("failures", 0)),
            consecutive_failures=int(raw.get("consecutive_failures", 0)),
            last_success_at=str(raw.get("last_success_at", "")),
            last_failure_at=str(raw.get("last_failure_at", "")),
            last_failure_note=str(raw.get("last_failure_note", "")),
            demoted=bool(raw.get("demoted", False)),
            demotion_reason=str(raw.get("demotion_reason", "")),
        )
        _STATS[name] = stat


def save_skill_stats(path: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(to_dict(), handle, ensure_ascii=False, indent=2)


def load_skill_stats(path: str) -> List[str]:
    """Load an audit file into memory; returns the restored skill names."""

    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    from_dict(data)
    return sorted(_STATS)


def rank_candidates(names: List[str]) -> List[str]:
    """Order skill names by priority (selection rule, design.md D5).

    Demoted names are excluded; ties on success rate keep the given
    (registration) order.  If every name is demoted, the original order
    is returned unchanged so callers can degrade explicitly.
    """

    eligible = [name for name in names if not is_demoted(name)]
    if not eligible:
        return list(names)
    return sorted(
        eligible,
        key=lambda name: -(
            get_skill_stat(name).success_rate if get_skill_stat(name) else 0.0
        ),
    )
