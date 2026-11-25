"""``step-rl`` — one entry point for deploying, operating and verifying Step-RL.

    step-rl doctor [--live] [--json]      deployment readiness of this machine
    step-rl studio [--host --port]        launch Step-RL Studio (web console)
    step-rl run "<instruction>"           run one task on the real local shop
    step-rl eval [--suite smoke|unified]  regression suite with verifier verdicts
    step-rl scenarios                     list curated Studio scenarios
    step-rl privacy-scan                  repository privacy gate
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import List, Optional

from . import __version__

LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def _utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass


def cmd_doctor(args: argparse.Namespace) -> int:
    from .ops.doctor import exit_code, render, run_checks

    results = run_checks(live=args.live, privacy=not args.no_privacy)
    print(render(results, as_json=args.json))
    return exit_code(results, strict=args.strict)


def cmd_studio(args: argparse.Namespace) -> int:
    if args.host not in LOOPBACK and not os.environ.get("CONSOLE_TOKEN"):
        print("refusing to bind a non-loopback host without CONSOLE_TOKEN (set it, or use --host 127.0.0.1)",
              file=sys.stderr)
        return 2
    import uvicorn

    print(f"Step-RL Studio v{__version__} → http://{args.host}:{args.port}")
    uvicorn.run("step_rl.console.app:app", host=args.host, port=args.port, log_level=args.log_level)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    from .ops.suites import Case, run_case, summarize, write_report

    case = Case(
        id="cli-run",
        instruction=args.instruction,
        expect={},
        layout=args.layout,
        perturb_ids=args.churn,
    )
    if args.scenario:
        from .ops.suites import smoke_cases

        match = [c for c in smoke_cases() if c.id == args.scenario]
        if not match:
            print(f"unknown scenario: {args.scenario}", file=sys.stderr)
            return 2
        case = match[0]
    if not case.expect:
        case = _run_unverified(case, args)
        return 0 if case else 1
    t0 = time.perf_counter()
    print(f"task: {case.instruction}\nexpect (server state): {case.expect}"
          f"{' · promo ' + case.expect_promo if case.expect_promo else ''} · layout {case.layout}\n")
    row = asyncio.run(run_case(case, headless=not args.headed, trace=True))
    summary = summarize([row], time.perf_counter() - t0)
    out = write_report("run", [row], summary)
    for i, step in enumerate(row.get("trace", []), 1):
        params = json.dumps(step["params"], ensure_ascii=False)
        print(f"  {i:>2} {'✓' if step['ok'] else '✗'} {step['source']:<6} {step['action']:<6} {params[:64]}")
    if "satisfied" in row:
        print(f"\nverifier Φ: {len(row['satisfied'])} satisfied · missing {row.get('missing') or 'none'}")
        print(f"server order: total={row.get('order_total')} paid={row.get('order_paid')}"
              f" promo={row.get('promo') or '—'} cart={row.get('cart')}\n")
    _print_row(row)
    print(f"\nevidence → {out.relative_to(Path.cwd()) if out.is_relative_to(Path.cwd()) else out}")
    return 0 if row.get("success") else 1


def _run_unverified(case, args) -> bool:
    """Free-form instruction: no pre-declared target, report the runtime verdict."""
    from .edge.browser import BrowserEnv
    from .edge.runtime import run_task
    from .edge.site import LocalShopServer
    from .edge.tasks import TaskSpec

    async def go() -> dict:
        server = LocalShopServer(layout=case.layout).start()
        channel = os.environ.get("STEP_RL_BROWSER_CHANNEL", "msedge")
        env = BrowserEnv(server, channel=None if channel == "chromium" else channel,
                         headless=not args.headed, semantic=True, perturb_ids=case.perturb_ids)
        try:
            await env.start()
            await env.reset(TaskSpec("cli", 3, case.instruction, "", {}))
            result = await run_task(env, case.instruction, None, None)
            state = await env.get_state()
            return {"result": result, "state": state}
        finally:
            await env.close()
            server.stop()

    out = asyncio.run(go())
    result, state = out["result"], out["state"]
    steps = result.get("steps", [])
    print(f"plan: {result.get('spec')}")
    for i, step in enumerate(steps, 1):
        action = getattr(step, "action", {}) or {}
        mark = "✓" if getattr(step, "exec_ok", False) else "✗"
        print(f"  {i:>2} {mark} {action.get('action', '?'):<8} {json.dumps(action.get('params', {}), ensure_ascii=False)[:70]}")
    order = state.get("order") or {}
    print(f"\nruntime verdict: {'SUCCESS' if result.get('success') else 'FAILED'}"
          f" · order={order.get('id', '—')} total={order.get('total', '—')} paid={order.get('paid', '—')}")
    if result.get("fallback_required"):
        print("not covered by compiled skills → needs LLM fallback (configure a model, see README)")
    return bool(result.get("success"))


def _print_row(row: dict) -> None:
    mark = "PASS" if row.get("success") else "FAIL"
    detail = row.get("error") or ("missing: " + ", ".join(row.get("missing", [])) if row.get("missing") else "")
    print(f"{mark}  {row['id']:<24} {row.get('skill_steps', 0):>3} skill · {row.get('policy_steps', 0)} LLM · "
          f"{row['seconds']:>6.2f}s  {row['instruction'][:34]}  {detail}")


def cmd_eval(args: argparse.Namespace) -> int:
    from .ops.suites import SUITES, run_suite, summarize, write_report

    cases = SUITES[args.suite]()
    if args.limit:
        cases = cases[: args.limit]
    print(f"step-rl eval · suite={args.suite} · {len(cases)} cases · concurrency={args.concurrency}\n")
    t0 = time.perf_counter()
    rows = asyncio.run(run_suite(cases, concurrency=args.concurrency, headless=not args.headed, on_result=_print_row))
    summary = summarize(rows, time.perf_counter() - t0)
    out = write_report(args.suite, rows, summary, Path(args.out) if args.out else None)
    print(f"\n{summary['passed']}/{summary['cases']} passed · {summary['llm_steps']} LLM steps · "
          f"{summary['skill_steps']} skill steps · wall {summary['wall_seconds']}s")
    print(f"report → {out}")
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["passed"] == summary["cases"] else 1


def cmd_scenarios(args: argparse.Namespace) -> int:
    from .console.scenarios import list_scenarios

    for s in list_scenarios():
        print(f"{s['id']:<18} {s['title']:<14} [{s['evidence']}]  {s['instruction']}")
    return 0


def cmd_privacy(args: argparse.Namespace) -> int:
    from .ops.privacy import load_terms, scan

    root = Path(args.root).resolve()
    findings = scan(root)
    if args.json:
        print(json.dumps([f.to_dict() for f in findings], ensure_ascii=False, indent=2))
    else:
        for f in findings:
            print(f"{f.path}:{f.line}  [{f.kind}]  {f.excerpt}")
        terms = len(load_terms(root))
        print(f"\nprivacy scan: {'CLEAN' if not findings else f'{len(findings)} finding(s)'}"
              f" · generic detectors + {terms} local term(s)")
    return 0 if not findings else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="step-rl", description="Step-RL — verifier-driven edge web agent")
    p.add_argument("--version", action="version", version=f"step-rl {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("doctor", help="check deployment readiness of this machine")
    d.add_argument("--live", action="store_true", help="also launch a real browser against the local shop")
    d.add_argument("--json", action="store_true")
    d.add_argument("--strict", action="store_true", help="exit 2 on warnings")
    d.add_argument("--no-privacy", action="store_true", help="skip the repository privacy gate")
    d.set_defaults(fn=cmd_doctor)

    s = sub.add_parser("studio", help="launch Step-RL Studio")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--log-level", default="warning")
    s.set_defaults(fn=cmd_studio)

    r = sub.add_parser("run", help="run one task on the real local shop")
    r.add_argument("instruction", nargs="?", default="")
    r.add_argument("--scenario", help="curated scenario id (see `step-rl scenarios`)")
    r.add_argument("--layout", default="v1", choices=["v1", "v2", "v3"])
    r.add_argument("--churn", action="store_true", help="randomise element ids every observation")
    r.add_argument("--headed", action="store_true", help="show the browser window")
    r.set_defaults(fn=cmd_run)

    e = sub.add_parser("eval", help="run a regression suite with verifier verdicts")
    e.add_argument("--suite", default="smoke", choices=["smoke", "unified"])
    e.add_argument("--concurrency", type=int, default=2)
    e.add_argument("--limit", type=int, default=0)
    e.add_argument("--out", default="")
    e.add_argument("--headed", action="store_true")
    e.add_argument("--json", action="store_true")
    e.set_defaults(fn=cmd_eval)

    sub.add_parser("scenarios", help="list curated Studio scenarios").set_defaults(fn=cmd_scenarios)

    pv = sub.add_parser("privacy-scan", help="scan the repository for private data")
    pv.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    pv.add_argument("--json", action="store_true")
    pv.set_defaults(fn=cmd_privacy)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    _utf8_stdout()
    args = build_parser().parse_args(argv)
    if args.cmd == "run" and not (args.instruction or args.scenario):
        print("give an instruction or --scenario", file=sys.stderr)
        return 2
    return int(args.fn(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
