"""Failure-driven skill induction (AR019).

When the capability gate reports a task as uncovered, the runtime falls back
to the real LLM hierarchy.  If that fallback *succeeds*, the trajectory is
recorded here, generalised into a parameterised skill template and registered
in the skill library, so the next task of the same operation runs with zero
LLM calls.

Everything in this module observes real executions: the recorder wraps a real
:class:`BrowserEnv` and never fabricates actions or observations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from .planner import CatalogItem
from .tasks import TaskSpec


@dataclass
class RecordedStep:
    """One real executed action, resolved against the observation it acted on."""

    kind: str  # goto / click / type
    url: str = ""
    role: str = ""
    name: str = ""
    value: str = ""


class TrajectoryRecorder:
    """Wrap a real BrowserEnv and record every executed action.

    ``observe()`` caches the semantic element table (eid -> role +
    accessible_name) of the *current* observation; ``execute()`` resolves the
    action against that table before delegating to the real environment.  The
    action itself is always really executed - the recorder never blocks,
    rewrites or fakes it.
    """

    def __init__(self, env: Any) -> None:
        self.env = env
        self.records: List[RecordedStep] = []
        self._elements: Dict[str, Dict[str, str]] = {}

    async def observe(self) -> Dict[str, Any]:
        obs = await self.env.observe()
        self._elements = {
            str(element.get("eid")): element for element in obs.get("elements", [])
        }
        return obs

    async def execute(self, action: Dict[str, Any]) -> Dict[str, Any]:
        name = str(action.get("action", "")).lower()
        params = action.get("params") or {}
        if name == "goto":
            self.records.append(
                RecordedStep(kind="goto", url=str(params.get("url", "/")))
            )
        elif name in ("click", "type"):
            meta = self._elements.get(str(params.get("element")), {})
            step = RecordedStep(
                kind=name,
                role=str(meta.get("role", "")),
                name=str(meta.get("accessible_name", "")),
            )
            if name == "type":
                step.value = str(params.get("text", ""))
            self.records.append(step)
        return await self.env.execute(action)

    def __getattr__(self, item: str) -> Any:
        return getattr(self.env, item)


def induce_skill(
    task: TaskSpec,
    records: List[RecordedStep],
    catalog: List[CatalogItem],
) -> Dict[str, Any]:
    """Generalise a successful trajectory into a parameterised template.

    Product names are replaced by ``{product}``; typed values that are pure
    digits equal to a target quantity become ``{qty}``.  ``goto`` steps keep
    their URL.  The template is JSON-serialisable and can be registered via
    ``skill_library.register_induced_skill``.
    """

    name_map = {item.name: "{product}" for item in catalog if item.name}
    target_qtys = {str(qty) for qty in task.targets.values() if qty}
    steps: List[Dict[str, Any]] = []
    for record in records:
        if record.kind == "goto":
            steps.append({"kind": "goto", "url": record.url})
            continue
        name = record.name
        for product_name, placeholder in name_map.items():
            if product_name in name:
                name = name.replace(product_name, placeholder)
        value = record.value
        if value.isdigit() and value in target_qtys:
            value = "{qty}"
        steps.append(
            {
                "kind": record.kind,
                "role": record.role,
                "name": name,
                "value": value,
            }
        )
    return {"name": f"induced_{task.operation}", "steps": steps}
