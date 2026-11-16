"""AR024: concurrency guarantees of the shared skill runtime.

These tests pin the invariants that concurrent sessions rely on:

* no lost verifier-confirmed outcome under parallel recording;
* concurrent reload + persist always leaves a parseable file equal to
  one writer's consistent snapshot (no mixed streams, no torn state);
* the registry upsert is atomic (no duplicate candidates);
* ``from_dict`` is an atomic replace (documented last-reloader-wins);
* the stdlib primitives (``atomic_write_json`` / ``run_concurrent``)
  behave as specified, including per-task exception isolation and
  real parallelism;
* serial semantics are unchanged (round-trips are field-for-field).

The race-heavy tests amplify the observable GIL hand-off window
(``sys.setswitchinterval(1e-6)``); on the locked implementation the
invariants hold regardless of the scheduler, which is the point.
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from typing import List

import pytest

from step_rl.edge import skill_library, skill_stats
from step_rl.edge.concurrency import atomic_write_json, run_concurrent
from step_rl.edge.tasks import TaskSpec

SWITCH = 1e-6


@pytest.fixture(autouse=True)
def _clean_state():
    skill_stats.clear_skill_stats()
    skill_library.clear_induced_skills()
    yield
    skill_stats.clear_skill_stats()
    skill_library.clear_induced_skills()


def _snapshot(idx: int, n: int = 12) -> dict:
    """Same-size distinct snapshots (equal byte length for clean mixes)."""

    skills = {}
    for j in range(n):
        skills[f"s{idx}_{j:02d}"] = {
            "name": f"s{idx}_{j:02d}",
            "operation": "op" + "x" * 10,
            "attempts": (j + 1) % 5,
            "successes": j % 3,
            "failures": j % 2,
            "consecutive_failures": j % 2,
            "last_success_at": "2026-01-01T00:00:0" + str(j % 10),
            "last_failure_at": "2026-01-01T00:00:0" + str(j % 10),
            "last_failure_note": "n" * 10,
            "demoted": j % 2 == 0,
            "demotion_reason": "r" * 10,
        }
    return {"policy": {"min_attempts": 1, "max_rate": 0.5},
            "skills": skills}


def test_no_lost_updates_successes():
    """8 threads x 50 successes -> exactly 400 recorded, no demotion."""

    old = sys.getswitchinterval()
    sys.setswitchinterval(SWITCH)
    try:
        n_thread, n_iter = 8, 50
        bar = threading.Barrier(n_thread)

        def worker() -> None:
            bar.wait()
            for _ in range(n_iter):
                skill_stats.record_skill_outcome("conc_ok", "add", True)

        threads = [threading.Thread(target=worker) for _ in range(n_thread)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        sys.setswitchinterval(old)

    stat = skill_stats.get_skill_stat("conc_ok")
    assert stat is not None
    assert stat.attempts == n_thread * n_iter
    assert stat.successes == n_thread * n_iter
    assert stat.failures == 0
    assert not stat.demoted


def test_no_lost_updates_failures():
    """8 threads x 50 failures -> exactly 400, demotion consistent."""

    old = sys.getswitchinterval()
    sys.setswitchinterval(SWITCH)
    try:
        n_thread, n_iter = 8, 50
        bar = threading.Barrier(n_thread)

        def worker() -> None:
            bar.wait()
            for _ in range(n_iter):
                skill_stats.record_skill_outcome(
                    "conc_bad", "remove", False, "dom miss"
                )

        threads = [threading.Thread(target=worker) for _ in range(n_thread)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        sys.setswitchinterval(old)

    stat = skill_stats.get_skill_stat("conc_bad")
    assert stat is not None
    assert stat.attempts == n_thread * n_iter
    assert stat.failures == n_thread * n_iter
    assert stat.demoted is True
    assert stat.last_failure_note == "dom miss"


def test_concurrent_save_parseable_single_snapshot(tmp_path):
    """8 writers x 6 rounds on one file: parseable, equals one snapshot."""

    path = tmp_path / "stats.json"
    snaps = [_snapshot(i) for i in range(8)]
    old = sys.getswitchinterval()
    sys.setswitchinterval(SWITCH)
    try:
        for _ in range(6):
            bar = threading.Barrier(8)

            def worker(idx: int) -> None:
                bar.wait()
                skill_stats.from_dict(snaps[idx])
                skill_stats.save_skill_stats(str(path))

            threads = [threading.Thread(target=worker, args=(i,))
                       for i in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            data = json.loads(path.read_text(encoding="utf-8"))
            assert data in snaps, "persisted file must be one whole snapshot"
    finally:
        sys.setswitchinterval(old)


def test_same_name_concurrent_upsert_single_candidate():
    """4 threads x 50 rounds re-registering one name -> exactly 1 entry."""

    old = sys.getswitchinterval()
    sys.setswitchinterval(SWITCH)
    try:
        n_thread, rounds = 4, 50
        for j in range(200):  # widen the name-scan window first
            skill_library.register_induced_skill(
                "conc_op",
                [{"kind": "goto", "name": f"decoy{j}", "role": "",
                  "value": "", "url": "/"}],
                name=f"decoy_{j}",
            )
        bar = threading.Barrier(n_thread)

        def worker(tid: int) -> None:
            for _ in range(rounds):
                bar.wait()
                skill_library.register_induced_skill(
                    "conc_op",
                    [{"kind": "goto", "name": f"t{tid}", "role": "",
                      "value": "", "url": "/"}],
                    name="same_name",
                )

        threads = [threading.Thread(target=worker, args=(i,))
                   for i in range(n_thread)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        sys.setswitchinterval(old)

    candidates = skill_library.induced_candidates("conc_op")
    same = [c for c in candidates if c["name"] == "same_name"]
    assert len(same) == 1
    assert len(candidates) == 201  # 200 decoys + the single upserted name


def test_from_dict_atomic_replace_semantics():
    """Serial total order: record -> reload (replace) -> record.

    The reload wipes the first record (replace, not merge) and the
    second record survives with exactly one attempt.
    """

    skill_stats.record_skill_outcome("x", "add", True)
    skill_stats.from_dict(_snapshot(0, n=3))
    assert skill_stats.get_skill_stat("x") is None
    skill_stats.record_skill_outcome("x", "add", True)
    stat = skill_stats.get_skill_stat("x")
    assert stat is not None and stat.attempts == 1
    loaded = skill_stats.get_skill_stat("s0_00")
    assert loaded is not None and loaded.attempts == 1


def test_record_vs_reload_concurrent_consistent():
    """Barrier races of record vs reload: no torn visible state.

    Invariant: the reloaded skill ``y`` is never mutated or partially
    installed; ``x`` is either absent (last op was a reload) or carries
    a whole count of its own successes (1..20, zero failures).
    """

    file = _snapshot(0, n=3)  # contains s0_* skills, no "x"
    old = sys.getswitchinterval()
    sys.setswitchinterval(SWITCH)
    try:
        rounds = 20
        bar = threading.Barrier(2)

        def recorder() -> None:
            for _ in range(rounds):
                bar.wait()
                skill_stats.record_skill_outcome("x", "add", True)

        def reloader() -> None:
            for _ in range(rounds):
                bar.wait()
                skill_stats.from_dict(file)

        a = threading.Thread(target=recorder)
        b = threading.Thread(target=reloader)
        a.start()
        b.start()
        a.join()
        b.join()
    finally:
        sys.setswitchinterval(old)

    y = skill_stats.get_skill_stat("s0_00")
    assert y is not None  # a reload always re-installs the file's skills
    # _snapshot(0, n=3): j=0 -> attempts=1, successes=0, failures=0
    assert y.attempts == 1 and y.successes == 0 and y.failures == 0
    x = skill_stats.get_skill_stat("x")
    if x is not None:
        assert 1 <= x.attempts <= rounds
        assert x.successes == x.attempts and x.failures == 0


def test_atomic_write_json_roundtrip_and_concurrent(tmp_path):
    """4 writers x 20 rounds: file always parseable, equals one payload."""

    path = tmp_path / "data.json"
    payloads = [{"w": i, "v": "x" * 400} for i in range(4)]
    old = sys.getswitchinterval()
    sys.setswitchinterval(SWITCH)
    try:
        for _ in range(20):
            bar = threading.Barrier(4)
            errors: List[BaseException] = []

            def worker(i: int) -> None:
                try:
                    bar.wait()
                    atomic_write_json(str(path), payloads[i])
                except BaseException as exc:  # hard assertion, no silent death
                    errors.append(exc)

            threads = [threading.Thread(target=worker, args=(i,))
                       for i in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            assert not errors, f"writer thread raised: {errors}"
            data = json.loads(path.read_text(encoding="utf-8"))
            assert data in payloads
    finally:
        sys.setswitchinterval(old)
    # no leftover temp files
    leftovers = [p.name for p in tmp_path.iterdir()
                 if p.name.startswith(".tmp_atomic_")]
    assert leftovers == []


async def _sleep_coro(value: float, name: str):
    await asyncio.sleep(value)
    return {"name": name, "value": value}


def test_run_concurrent_results_and_error_isolation():
    """Input-ordered results; one raising task isolates to its slot."""

    async def boom():
        raise ValueError("isolated")

    results, _ = run_concurrent([
        _sleep_coro(0.05, "a"),
        boom(),
        _sleep_coro(0.05, "c"),
        _sleep_coro(0.05, "d"),
    ])
    assert results[0] == {"name": "a", "value": 0.05}
    assert isinstance(results[1], dict)
    assert "ValueError" in results[1]["error"]
    assert results[2] == {"name": "c", "value": 0.05}
    assert results[3] == {"name": "d", "value": 0.05}


def test_run_concurrent_parallelism():
    """4 x 0.2s sleep: wall time must be far below the serial sum."""

    results, wall = run_concurrent([_sleep_coro(0.2, f"t{i}")
                                   for i in range(4)])
    assert all(r["name"] == f"t{i}" for i, r in enumerate(results))
    assert wall < 0.8  # serial would be >= 0.8
    assert wall >= 0.15  # ...but the sleeps really happened


def test_serial_roundtrip_unchanged(tmp_path):
    """register -> record -> save -> clear -> load restores everything."""

    template = [
        {"kind": "goto", "url": "/cart", "name": "", "role": "", "value": ""},
        {"kind": "click", "name": "移除 {product}", "role": "button",
         "value": ""},
    ]
    skill_library.register_induced_skill("remove", template, "rt_skill")
    skill_stats.record_skill_outcome("rt_skill", "remove", True)
    skill_stats.record_skill_outcome("rt_skill", "remove", False)
    stats_path = tmp_path / "stats.json"
    skills_path = tmp_path / "skills.json"
    skill_stats.save_skill_stats(str(stats_path))
    skill_library.save_induced_skills(str(skills_path))

    skill_stats.clear_skill_stats()
    skill_library.clear_induced_skills()
    skill_stats.load_skill_stats(str(stats_path))
    loaded = skill_library.load_induced_skills(str(skills_path))
    assert loaded == ["remove"]

    stat = skill_stats.get_skill_stat("rt_skill")
    assert stat is not None
    assert (stat.attempts, stat.successes, stat.failures) == (2, 1, 1)
    assert stat.demoted is False
    candidates = skill_library.induced_candidates("remove")
    assert len(candidates) == 1
    assert candidates[0]["name"] == "rt_skill"
    assert candidates[0]["steps"] == template


def test_concurrent_save_induced_skills(tmp_path):
    """4 concurrent persists of one registry: parseable, legal shape."""

    for j in range(5):
        skill_library.register_induced_skill(
            f"op_{j % 2}",
            [{"kind": "goto", "name": f"step{j}", "role": "", "value": "",
              "url": "/"}],
            name=f"cand_{j}",
        )
    path = tmp_path / "induced.json"
    old = sys.getswitchinterval()
    sys.setswitchinterval(SWITCH)
    try:
        bar = threading.Barrier(4)
        errors: List[BaseException] = []

        def worker() -> None:
            try:
                bar.wait()
                skill_library.save_induced_skills(str(path))
            except BaseException as exc:  # hard assertion, no silent death
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors, f"persist thread raised: {errors}"
    finally:
        sys.setswitchinterval(old)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data) == {"op_0", "op_1"}
    for entry in data.values():
        assert set(entry) == {"name", "steps"}
        assert entry["steps"]


def remove_task(pid: str) -> TaskSpec:
    return TaskSpec(
        task_id="rm_probe",
        level=2,
        goal="probe",
        search_query="x",
        targets={pid: 0},
        operation="remove",
        predicates=["cart_without"],
        start_path="/cart",
        seed_cart={pid: 1},
    )


def test_selection_rule_serial_unchanged():
    """Demoted candidate yields; the healthy one is materialised (AR021)."""

    skill_library.register_induced_skill(
        "remove",
        [{"kind": "click", "name": "移除 {product}", "role": "button",
          "value": ""}],
        name="stale_one",
    )
    skill_library.register_induced_skill(
        "remove",
        [{"kind": "click", "name": "移除 {product}", "role": "button",
          "value": ""}],
        name="good_two",
    )
    # real outcomes: stale_one 0/1 -> demoted; good_two 1/1 -> kept
    for _ in range(2):
        skill_stats.record_skill_outcome("stale_one", "remove", False)
    skill_stats.reset_skill_stats("stale_one")
    skill_stats.record_skill_outcome("stale_one", "remove", False)
    skill_stats.record_skill_outcome("good_two", "remove", True)

    skill = skill_library.skill_for_subtask(remove_task("p3"))
    assert skill is not None
    assert skill.name == "good_two"
