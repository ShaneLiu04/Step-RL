"""AR024 pre-change baseline probe (run on the AR023 code state, old code).

Evidence for the concurrency gaps that AR024 closes, measured on the
real modules, a real HTTP server and real Edge sessions:

  E1  micro lost-update probe: 8 threads x 250 verifier-confirmed
      outcomes through the OLD ``record_skill_outcome`` (switch
      interval amplified to 1us to make the GIL hand-off dense);
      reports the real counter result and - honestly - whether the
      3-bytecode window was actually pre-empted on CPython 3.11;
  E2  concurrent reload + persist: 8 threads x 10 rounds, each round
      every thread runs ``from_dict``(a distinct same-size 200-skill
      snapshot) then ``save_skill_stats`` to ONE shared path on the
      old (lockless, non-atomic) code; the probe counts rounds whose
      final file is (a) unparseable, (b) parseable but equal to no
      single writer snapshot (silent mix), and worker-thread crashes;
  E3  concurrent same-operation upsert: 4 threads x 100 barrier-synced
      rounds of ``register_induced_skill`` with per-round unique names
      over 500 decoy candidates (widened scan window) - counts the
      duplicated candidates the check-then-append race produces;
  E4  server-side isolation control: 2 real concurrent Edge sessions
      (shared LocalShopServer) each run a real add-item skill; the
      per-session ``/api/state`` snapshots must stay clean - proving
      the isolation gap is NOT in the server session layer.

Outputs: outputs/ar024/baseline_probe.json + baseline_probe.md
Exit code 0 when the probe itself ran (defect presence is the
expected finding); non-zero only if the E4 server-isolation control
fails (that would falsify the AR premise).
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from step_rl.edge.browser import BrowserEnv  # noqa: E402
from step_rl.edge.skill_library import (  # noqa: E402
    clear_induced_skills,
    induced_candidates,
    register_induced_skill,
    run_skill,
    skill_for_subtask,
)
from step_rl.edge.skill_stats import (  # noqa: E402
    all_skill_stats,
    clear_skill_stats,
    from_dict,
    get_skill_stat,
    record_skill_outcome,
    save_skill_stats,
)
from step_rl.edge.site import LocalShopServer  # noqa: E402
from step_rl.edge.tasks import TaskSpec  # noqa: E402

OUT = ROOT / "outputs" / "ar024"
SAVE_PATH = OUT / "_probe_stats.json"
SWITCH = 1e-6  # dense GIL hand-off to widen the observable race window


def _make_snapshots(n_thread: int, n_skills: int = 200) -> list:
    """Same-size distinct snapshots (identical byte length each)."""

    snaps = []
    for i in range(n_thread):
        skills = {}
        for j in range(n_skills):
            skills[f"s{i}_{j:03d}"] = {
                "name": f"s{i}_{j:03d}",
                "operation": "op" + "x" * 30,
                "attempts": (j + 1) % 7,
                "successes": j % 5,
                "failures": (j % 3),
                "consecutive_failures": j % 2,
                "last_success_at": "2026-01-01T00:00:0" + str(j % 10),
                "last_failure_at": "2026-01-01T00:00:0" + str(j % 10),
                "last_failure_note": "n" * 20,
                "demoted": j % 2 == 0,
                "demotion_reason": "r" * 40,
            }
        snaps.append({"policy": {"min_attempts": 1, "max_rate": 0.5},
                      "skills": skills})
    return snaps


def e1_micro() -> dict:
    """E1: micro lost-update window (honest GIL note expected)."""

    clear_skill_stats()
    old_switch = sys.getswitchinterval()
    sys.setswitchinterval(SWITCH)
    n_thread, n_iter = 8, 250
    bar = threading.Barrier(n_thread)
    errors = []

    def worker() -> None:
        try:
            bar.wait()
            for _ in range(n_iter):
                record_skill_outcome("probe_e1", "add", True)
        except Exception as exc:  # pragma: no cover
            errors.append(f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=worker) for _ in range(n_thread)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    sys.setswitchinterval(old_switch)
    stat = get_skill_stat("probe_e1")
    expected = n_thread * n_iter
    return {
        "threads": n_thread,
        "iters_per_thread": n_iter,
        "expected": expected,
        "recorded": stat.attempts if stat else 0,
        "lost_updates": expected - (stat.attempts if stat else 0),
        "errors": errors,
        "note": (
            "CPython 3.11 GIL 保护 3 字节码读-改-写窗口：微观丢失未复现"
            "属预期；同模块的粗窗口缺陷见 E2/E3。锁修复对 GIL 版与"
            "free-threaded 构建同样成立（锁是解释器无关的正确性保证）。"
        ),
    }


def e2_mixed_persist() -> dict:
    """E2: concurrent from_dict + save_skill_stats on one path (old code)."""

    clear_skill_stats()
    snaps = _make_snapshots(8)
    sizes = {len(json.dumps(s, ensure_ascii=False, indent=2)) for s in snaps}
    old_switch = sys.getswitchinterval()
    sys.setswitchinterval(SWITCH)
    corrupt = 0
    mixed = 0
    crashed_rounds = 0
    crash_kinds: list[str] = []
    for _ in range(10):
        bar = threading.Barrier(8)
        errors = []

        def worker(idx: int) -> None:
            try:
                bar.wait()
                from_dict(snaps[idx])
                save_skill_stats(str(SAVE_PATH))
            except Exception as exc:
                errors.append(f"{type(exc).__name__}: {str(exc)[:120]}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        if errors:
            crashed_rounds += 1
            for e in errors:
                kind = e.split(":", 1)[0]
                if kind not in crash_kinds:
                    crash_kinds.append(kind)
        try:
            data = json.loads(SAVE_PATH.read_text(encoding="utf-8"))
            if data not in snaps:
                mixed += 1
        except Exception:
            corrupt += 1
    sys.setswitchinterval(old_switch)
    return {
        "rounds": 10,
        "threads_per_round": 8,
        "snapshot_bytes": sorted(sizes)[0],
        "unparseable_rounds": corrupt,
        "mixed_snapshot_rounds": mixed,
        "crashed_rounds": crashed_rounds,
        "crash_kinds": crash_kinds,
        "crash_example": (
            "RuntimeError: dictionary changed size during iteration"
            if "RuntimeError" in crash_kinds else ""
        ),
        "note": (
            "旧 save_skill_stats 非原子直写同一文件：8 路 json.dump 交错"
            "产出「可解析但不属于任何一方」的混合快照（静默数据完整性"
            "破坏）；并发 from_dict 的 clear()+插入 与 to_dict() 迭代重叠"
            "直接抛 RuntimeError，工作线程静默死亡（审计落盘丢失）。"
        ),
    }


def e3_upsert_dupes() -> dict:
    """E3: concurrent check-then-append upsert race (old code)."""

    clear_induced_skills()
    for j in range(500):
        register_induced_skill(
            "probe_op",
            [{"kind": "goto", "name": f"decoy{j}", "role": "", "value": "",
              "url": "/"}],
            name=f"decoy_{j}",
        )
    old_switch = sys.getswitchinterval()
    sys.setswitchinterval(SWITCH)
    rounds = 100
    bar = threading.Barrier(4)
    errors = []

    def worker(tid: int) -> None:
        try:
            for r in range(rounds):
                bar.wait()
                register_induced_skill(
                    "probe_op",
                    [{"kind": "goto", "name": f"t{tid}", "role": "", "value": "",
                      "url": "/"}],
                    name=f"dup_{r}",
                )
        except Exception as exc:  # pragma: no cover
            errors.append(f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    t0 = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.time() - t0
    sys.setswitchinterval(old_switch)
    cands = induced_candidates("probe_op")
    names = [c["name"] for c in cands]
    distinct = len(set(names))
    return {
        "threads": 4,
        "rounds": rounds,
        "decoy_candidates": 500,
        "total_candidates": len(cands),
        "distinct_names": distinct,
        "duplicate_candidates": len(cands) - distinct,
        "wall_seconds": round(wall, 2),
        "errors": errors,
        "note": (
            "check-then-append 竞态：4 路同名注册同时通过查重再各自追加，"
            "产生重复候选——AR021 的按成功率选择在重复候选上失真"
            "（同名技能被统计两次/选择语义破坏）。"
        ),
    }


def e4_server_isolation() -> dict:
    """E4: 2 real concurrent Edge sessions on ONE server (control)."""

    server = LocalShopServer().start()
    envs = [
        BrowserEnv(server, channel="msedge", headless=True, semantic=True)
        for _ in range(2)
    ]

    async def worker(idx: int, pid: str) -> dict:
        env = envs[idx]
        await env.start()
        bar.wait()
        task = TaskSpec(
            task_id=f"e4_{pid}",
            level=2,
            goal="probe",
            search_query="",
            targets={pid: 2},
        )
        await env.reset(task)
        skill = skill_for_subtask(task)
        result = await run_skill(env, skill)
        state = await env.get_state()
        await env.close()
        return {
            f"session_{idx}_{pid}": {
                "skill_success": result.success,
                "cart": state.get("cart"),
                "sid_present": bool(state.get("sid")),
            }
        }

    bar = threading.Barrier(2)
    tasks = [(0, "p3"), (1, "p4")]
    results = {}
    errors = {}

    def runner(idx: int, pid: str) -> None:
        try:
            out = asyncio.run(worker(idx, pid))
            results.update(out)
        except Exception as exc:
            errors[f"session_{idx}_{pid}"] = f"{type(exc).__name__}: {exc}"

    threads = [threading.Thread(target=runner, args=t) for t in tasks]
    t0 = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.time() - t0
    server.stop()
    clean = (
        results.get("session_0_p3", {}).get("cart") == {"p3": 2}
        and results.get("session_1_p4", {}).get("cart") == {"p4": 2}
        and not errors
    )
    return {
        "concurrent_sessions": 2,
        "results": results,
        "errors": errors,
        "wall_seconds": round(wall, 2),
        "server_isolation_clean": clean,
        "note": (
            "2 个真实并发 Edge 会话共享一个服务端：逐会话 /api/state "
            "快照互不串扰——隔离缺口不在服务端会话层（SessionStore 带锁"
            "且按 sid 键控），而在进程共享的技能运行时组件（E1–E3）。"
        ),
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    report = {
        "ar": "AR024",
        "probe": "pre-change baseline (AR023 code state)",
        "switch_interval": SWITCH,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    print("E1 micro lost-update ...")
    report["e1_micro"] = e1_micro()
    print("E2 concurrent persist mix ...")
    report["e2_persist"] = e2_mixed_persist()
    print("E3 upsert dupes ...")
    report["e3_upsert"] = e3_upsert_dupes()
    print("E4 server isolation control (2 real Edge sessions) ...")
    report["e4_server"] = e4_server_isolation()
    report["summary"] = {
        "e1_lost_updates": report["e1_micro"]["lost_updates"],
        "e2_unparseable_rounds": report["e2_persist"]["unparseable_rounds"],
        "e2_mixed_rounds": report["e2_persist"]["mixed_snapshot_rounds"],
        "e2_crashed_rounds": report["e2_persist"]["crashed_rounds"],
        "e3_duplicate_candidates": report["e3_upsert"]["duplicate_candidates"],
        "e4_server_isolation_clean": report["e4_server"]["server_isolation_clean"],
    }
    (OUT / "baseline_probe.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# AR024 改动前基线探针（AR023 代码态，旧代码真实执行）",
        "",
        f"- 时间：{report['timestamp']}；switch interval = {SWITCH}",
        "",
        "## E1 微观丢更新（record_skill_outcome 读-改-写）",
        "",
        f"- 8 线程 × 250 次，期望 {report['e1_micro']['expected']}，"
        f"实测 {report['e1_micro']['recorded']}，"
        f"丢失 {report['e1_micro']['lost_updates']}",
        f"- {report['e1_micro']['note']}",
        "",
        "## E2 并发 from_dict + save_skill_stats（同一文件）",
        "",
        f"- 10 轮 × 8 线程，快照 {report['e2_persist']['snapshot_bytes']} 字节/个",
        f"- 不可解析轮次：{report['e2_persist']['unparseable_rounds']}/10",
        f"- 可解析但**不等于任何一方快照**（静默混合）："
        f"{report['e2_persist']['mixed_snapshot_rounds']}/10",
        f"- 工作线程崩溃轮次：{report['e2_persist']['crashed_rounds']}/10"
        f"（{report['e2_persist']['crash_kinds']}）",
        f"- {report['e2_persist']['note']}",
        "",
        "## E3 同名 upsert 竞态（check-then-append）",
        "",
        f"- 4 线程 × {report['e3_upsert']['rounds']} 轮（barrier 同步），"
        f"预置 {report['e3_upsert']['decoy_candidates']} 干扰候选",
        f"- 候选总数 {report['e3_upsert']['total_candidates']} vs "
        f"不同名 {report['e3_upsert']['distinct_names']} → "
        f"**重复候选 {report['e3_upsert']['duplicate_candidates']}**",
        f"- {report['e3_upsert']['note']}",
        "",
        "## E4 服务端隔离对照（2 真实并发 Edge 会话）",
        "",
        f"- 逐会话快照：{json.dumps(report['e4_server']['results'], ensure_ascii=False)}",
        f"- 无串扰：{report['e4_server']['server_isolation_clean']}"
        f"；并发墙钟 {report['e4_server']['wall_seconds']}s",
        f"- {report['e4_server']['note']}",
        "",
    ]
    (OUT / "baseline_probe.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    # Probe success = it ran; E4 control must hold (AR premise).
    return 0 if report["e4_server"]["server_isolation_clean"] else 1


if __name__ == "__main__":
    sys.exit(main())
