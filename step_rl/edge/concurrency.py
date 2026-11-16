"""Concurrency primitives for the multi-session edge runtime (AR024).

The single-session runtime of AR011-AR023 never had to share
process-wide state between concurrent sessions.  This module provides
the two building blocks that make concurrent sessions safe and
measurable:

* :func:`atomic_write_json` - persist a consistent snapshot to a file
  such that a reader always sees either the old or the new file, never
  a half-written or mixed stream (temp file in the *same directory* +
  ``os.replace``);
* :func:`run_concurrent` - execute a list of async workloads truly
  concurrently (one thread + one event loop per task; the Playwright
  async driver is not thread-shareable) with per-task exception
  isolation and an input-ordered result list.

Standard library only: no third-party concurrency dependency.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import threading
import time
from typing import Any, List, Optional, Tuple

# Bounded retry for the *move only* (the payload is already on disk in the
# temp file, so re-issuing ``os.replace`` cannot re-write partial content).
# On Windows a concurrent replace of the same target can transiently refuse
# the move (WinError 5/32) while the OS settles the previous rename.
_REPLACE_RETRIES = 6
_REPLACE_BACKOFF_S = 0.005


def _replace_with_retry(tmp: str, target: str) -> None:
    """``os.replace`` with bounded backoff on transient move failures."""

    last: Optional[OSError] = None
    for attempt in range(_REPLACE_RETRIES):
        try:
            os.replace(tmp, target)
            return
        except OSError as exc:
            last = exc
            time.sleep(_REPLACE_BACKOFF_S * (attempt + 1))
    assert last is not None
    raise last


def atomic_write_json(path: str, data: Any) -> None:
    """Write ``data`` as JSON so readers see old-or-new only.

    The full payload goes to a temporary file in the same directory as
    the target, then the file is swapped into place atomically (on
    Windows ``os.replace`` maps to ``MoveFileEx`` with
    ``REPLACE_EXISTING``).  The move retries with bounded backoff on the
    transient refusal Windows raises when several writers race the same
    target; a persistent failure still propagates.  On any failure the
    temp file is removed and the existing target left untouched, so a
    failed persist can never leave a half-written file behind.
    """

    target = os.fspath(path)
    directory = os.path.dirname(os.path.abspath(target)) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp_atomic_",
                               suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        _replace_with_retry(tmp, target)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def run_concurrent(
    coros: List[Any], name_prefix: str = "session"
) -> Tuple[List[Any], float]:
    """Run async workloads concurrently; one thread + event loop each.

    ``results[i]`` is the outcome of ``coros[i]`` (input order is
    preserved).  An exception in one task is isolated into its slot as
    ``{"error": "Type: message"}`` and never prevents the other tasks
    from completing.  Returns ``(results, wall_seconds)`` where the wall
    time is the evidence of real parallelism (≈ max(task) not
    sum(tasks)).
    """

    results: List[Any] = [None] * len(coros)
    threads: List[threading.Thread] = []
    start = time.perf_counter()

    def runner(index: int, coro: Any) -> None:
        try:
            results[index] = asyncio.run(coro)
        except BaseException as exc:  # isolated per task by design
            results[index] = {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}

    for index, coro in enumerate(coros):
        thread = threading.Thread(
            target=runner, args=(index, coro),
            name=f"{name_prefix}_{index}", daemon=True,
        )
        threads.append(thread)
        thread.start()
    for thread in threads:
        thread.join()
    return results, time.perf_counter() - start
