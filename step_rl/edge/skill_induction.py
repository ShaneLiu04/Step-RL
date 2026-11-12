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
from typing import Any, Dict, List, Optional

from .planner import CatalogItem
from .site import PRODUCTS
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


def _step_key(step: Dict[str, Any]) -> tuple:
    return (
        str(step.get("kind", "")),
        str(step.get("role", "")),
        str(step.get("name", "")),
        str(step.get("value", "")),
    )


def collapse_repeated_product_steps(steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Collapse consecutive steps that are identical after substitution.

    A batch trajectory records one step per product; after the product name
    becomes ``{product}`` the repeated per-product steps are indistinguishable.
    Collapsing them back to the single per-product unit is the same class of
    generalisation as the name substitution itself.  Single-product
    trajectories have no consecutive identical steps, so this is a no-op
    there and AR019 outputs are unchanged.
    """

    out: List[Dict[str, Any]] = []
    for step in steps:
        if out and _step_key(out[-1]) == _step_key(step):
            continue
        out.append(dict(step))
    return out


def _generalise_record(
    record: RecordedStep,
    name_map: Dict[str, str],
    target_qtys: set,
) -> Dict[str, Any]:
    """One recorded step -> template step (``{product}``/``{qty}`` swap)."""

    if record.kind == "goto":
        return {"kind": "goto", "url": record.url}
    name = record.name
    for product_name, placeholder in name_map.items():
        if product_name in name:
            name = name.replace(product_name, placeholder)
    value = record.value
    if value.isdigit() and value in target_qtys:
        value = "{qty}"
    return {
        "kind": record.kind,
        "role": record.role,
        "name": name,
        "value": value,
    }


def induce_skill(
    task: TaskSpec,
    records: List[RecordedStep],
    catalog: List[CatalogItem],
) -> Dict[str, Any]:
    """Generalise a successful trajectory into a parameterised template.

    Product names are replaced by ``{product}``; typed values that are pure
    digits equal to a target quantity become ``{qty}``.  ``goto`` steps keep
    their URL.  Consecutive identical steps are collapsed (a no-op for
    single-product trajectories, AR019 outputs unchanged).  The template is
    JSON-serialisable and can be registered via
    ``skill_library.register_induced_skill``.
    """

    name_map = {
        item.name: "{product}"
        for item in catalog
        if item.name
    }
    target_qtys = {str(qty) for qty in task.targets.values() if qty}
    steps = [
        _generalise_record(record, name_map, target_qtys) for record in records
    ]
    steps = collapse_repeated_product_steps(steps)
    return {"name": f"induced_{task.operation}", "steps": steps}


def _referenced_product(record: RecordedStep, names: List[str]) -> Optional[str]:
    haystack = f"{record.name} {record.value}"
    for name in names:
        if name and name in haystack:
            return name
    return None


def _common_suffix(a: List[Dict[str, Any]], b: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The longest list of steps that is a suffix of both ``a`` and ``b``."""

    limit = min(len(a), len(b))
    k = 0
    while k < limit and a[-1 - k] == b[-1 - k]:
        k += 1
    return a[-k:] if k else []


def induce_batch_template(
    task: TaskSpec,
    records: List[RecordedStep],
    catalog: List[CatalogItem],
) -> Optional[Dict[str, Any]]:
    """Generalise a multi-product remove trajectory (AR020).

    The trajectory is segmented into per-product blocks at each real
    ``移除 <product>`` click.  A block's *core* runs from its first
    product-referencing record to that removal click.  The fallback LLM is
    not exactly repeatable (the real P1 trajectory ran ``更新数量`` for the
    first product but removed the second directly), so the per-product unit
    is the **longest common suffix** of the generalised blocks: the
    minimal pattern that demonstrably removed *every* product.  Every block
    of a successful trajectory ends at its own removal click, so the common
    suffix ends at ``移除 {product}`` and is non-empty; ``None`` (an
    explicit capability gap) is kept as the defensive invariant.  Leading
    records that reference no product form the prefix; other
    non-referencing records are fallback-LLM noise and are dropped.
    A template is never fabricated from a trajectory without at least two
    blocks.
    """

    if len(task.targets) < 2:
        return None
    target_names = [
        (PRODUCTS[pid].name if pid in PRODUCTS else pid)
        for pid in task.targets
    ]
    name_map = {item.name: "{product}" for item in catalog if item.name}
    target_qtys = {str(qty) for qty in task.targets.values() if qty}

    prefix_records: List[RecordedStep] = []
    blocks: List[List[RecordedStep]] = []
    core: List[RecordedStep] = []
    current_product: Optional[str] = None
    for record in records:
        ref = _referenced_product(record, target_names)
        if current_product is None:
            if ref is None:
                prefix_records.append(record)
                continue
            current_product = ref
            core = [record]
        else:
            core.append(record)
        if (
            record.kind == "click"
            and record.name.startswith("移除")
            and current_product in record.name
        ):
            blocks.append(list(core))
            core = []
            current_product = None

    if len(blocks) < 2:
        return None
    generalised = [
        [_generalise_record(record, name_map, target_qtys) for record in block]
        for block in blocks
    ]
    unit: List[Dict[str, Any]] = list(generalised[0])
    for steps_list in generalised[1:]:
        unit = _common_suffix(unit, steps_list)
        if not unit:
            return None
    steps = [
        _generalise_record(record, name_map, target_qtys)
        for record in prefix_records
    ]
    steps.extend(unit)
    return {"name": f"induced_{task.operation}", "steps": steps}
