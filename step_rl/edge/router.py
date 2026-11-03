"""Task-type router for composing specialised LoRA adapters.

Different ARs can specialise on different skills.  Instead of forcing one
adapter to dominate, the router picks an adapter from *deployment-known task
metadata* (does the task require checkout? does it require a quantity > 1?).
It never inspects the evaluation outcome.
"""

from __future__ import annotations

from typing import Dict

from .tasks import TaskSpec


def route_adapter(task: TaskSpec, adapters: Dict[str, str]) -> str:
    """Return the adapter key for a task.

    Policy:
    * checkout / multi-item tasks -> ``checkout`` adapter (preserves flow);
    * quantity tasks (qty >= 2, no checkout) -> ``quantity`` adapter (VGDP);
    * everything else -> ``base`` adapter.
    """

    if task.require_checkout:
        return "checkout" if "checkout" in adapters else "base"
    if any(qty >= 2 for qty in task.targets.values()):
        return "quantity" if "quantity" in adapters else "base"
    return "base"
