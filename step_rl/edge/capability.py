"""Capability manifest: can the compiled skills handle this instruction?"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from .hierarchical import decompose_task
from .planner import CatalogItem, plan_instruction
from .skill_library import skill_for_subtask


@dataclass
class Capability:
    covered: bool
    reason: str
    skills: List[str]
    targets: Optional[Dict[str, int]] = None


def check_capability(instruction: str, catalog: List[CatalogItem]) -> Capability:
    spec = plan_instruction(instruction, catalog)
    if spec is None:
        return Capability(False, "planner_unsupported", [], None)
    skills = []
    for subtask in decompose_task(spec):
        skill = skill_for_subtask(subtask)
        if skill is None:
            return Capability(
                False, f"no_skill_for_level_{subtask.level}", skills, dict(spec.targets)
            )
        skills.append(skill.name)
    return Capability(True, "covered", skills, dict(spec.targets))
