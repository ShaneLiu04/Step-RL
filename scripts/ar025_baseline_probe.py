"""AR025 pre-change probe: real-Edge legacy 4-round-trip observation cost.

This monkeypatches the current BrowserEnv with the exact pre-AR025 observation
sequence (elements -> inner_text -> /api/state -> title) so the baseline is
measured on the same 30 real scenarios, not fabricated.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import scripts.ar011_eval as ar011  # noqa: E402
from step_rl.edge import browser as browser_mod  # noqa: E402
from step_rl.edge import skill_library as skill_mod  # noqa: E402

OUT = ROOT / "outputs" / "ar025"
M = {"calls": 0, "seconds": 0.0, "adjacent_dups": 0, "roundtrips": 0}


def _fingerprint(obs):
    return json.dumps(
        {
            "url": obs.get("url"),
            "title": obs.get("title"),
            "text": obs.get("text"),
            "elements": obs.get("elements"),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


async def legacy_observe(self):
    if self._page is None:
        raise RuntimeError("BrowserEnv not started")
    started = time.perf_counter()
    self.current_url = self._page.url
    raw = await self._page.evaluate(browser_mod._OBSERVE_JS)
    M["roundtrips"] += 1
    elements = raw.get("elements", [])
    priority = {"input": 0, "button": 1, "a": 2, "select": 3, "textarea": 4}
    elements.sort(key=lambda e: (priority.get(e["tag"], 9), e["selector"]))
    elements = elements[: self.max_elements]
    body_text = ""
    try:
        body_text = (await self._page.inner_text("body"))[:600]
    except Exception:
        pass
    M["roundtrips"] += 2  # inner_text + get_state
    state = await self.get_state()
    title = await self._page.title()
    M["roundtrips"] += 1
    obs = {
        "url": self.page_url_path,
        "title": title,
        "elements": elements,
        "text": body_text,
        "state": state,
    }
    M["calls"] += 1
    M["seconds"] += time.perf_counter() - started
    fp = _fingerprint(obs)
    prev = getattr(self, "_ar025_prev_fp", None)
    if prev == fp:
        M["adjacent_dups"] += 1
    self._ar025_prev_fp = fp
    return obs


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    browser_mod.BrowserEnv.observe = legacy_observe
    # Pre-AR025 call graph: run_skill always observed first, and the hierarchy
    # observed once more after the skill.  Emulate it on the same real tasks.
    _orig_run_skill = skill_mod.run_skill

    async def legacy_run_skill(env, skill, initial_obs=None):
        result = await _orig_run_skill(env, skill, initial_obs=None)
        result.observation = await env.observe()
        return result

    skill_mod.run_skill = legacy_run_skill
    await ar011.main()
    summary_path = ROOT / "outputs" / "ar011" / "eval" / "ar011_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    payload = {
        "ar": "AR025",
        "probe": "pre-change legacy 4-round-trip observation",
        "scenarios": summary["tasks"],
        "success_rate": summary["success_rate"],
        "policy_steps": summary["policy_steps"],
        "skill_steps": summary["skill_steps"],
        "observe_calls": M["calls"],
        "observe_seconds": round(M["seconds"], 2),
        "observe_roundtrips": M["roundtrips"],
        "adjacent_duplicate_snapshots": M["adjacent_dups"],
        "duplicate_ratio": round(M["adjacent_dups"] / max(1, M["calls"]), 4),
        "wall_seconds": summary["seconds"],
    }
    (OUT / "baseline_probe.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
