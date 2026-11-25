"""Step-RL Studio (AR035): live agent runs on a real browser, gated and audited.

The console drives the deterministic runtime (compiled skills + verifier) on
the real local shop through system Edge.  Every executed action is observed
through ``BrowserEnv.action_hooks``: the Studio streams per-step frames and
authoritative server state, can genuinely pause between actions, and holds
order submission until a human approves when the approval gate is on.
"""

from __future__ import annotations

import asyncio
import base64
import hmac
import json
import os
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import __version__
from ..edge.browser import BrowserEnv
from ..edge.runtime import run_task
from ..edge.site import PRODUCTS, PROMOS, LocalShopServer
from ..edge.tasks import TaskSpec
from ..logging_utils import get_logger
from .evidence import build_evidence
from .scenarios import get_scenario, list_scenarios
from .skills import build_skills

VERSION = __version__
ROOT = Path(__file__).resolve().parent.parent.parent
STATIC = Path(__file__).resolve().parent / "static"
AUDIT_ROOT = ROOT / "outputs" / "studio" / "sessions"
MAX_ACTIVE = 2
MAX_SESSIONS = 50
MAX_INSTRUCTION = 200
APPROVAL_LABELS = ("提交订单",)
ACTIVE = {"created", "starting", "running", "paused", "awaiting_approval"}
TERMINAL = {"success", "failed", "error", "cancelled"}
_SESSION_ID = re.compile(r"^[0-9a-f]{12}$")
logger = get_logger("step_rl.console")


def require_token(x_console_token: Optional[str] = Header(default=None)) -> None:
    expected = os.environ.get("CONSOLE_TOKEN", "")
    if expected and not hmac.compare_digest(x_console_token or "", expected):
        raise HTTPException(status_code=401, detail="console token required")


class RunRequest(BaseModel):
    instruction: str = ""
    site: str = "local"
    scenario: Optional[str] = None
    require_approval: bool = False


class StudioBusy(RuntimeError):
    """Raised when the active-session limit is reached."""


def _cart_view(cart: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    for pid, qty in sorted((cart or {}).items()):
        product = PRODUCTS.get(pid)
        if product is None or not qty:
            continue
        rows.append(
            {
                "pid": pid,
                "name": product.name,
                "price": product.price,
                "qty": int(qty),
                "subtotal": product.price * int(qty),
            }
        )
    return rows


class Session:
    def __init__(
        self,
        site: str,
        instruction: str,
        *,
        scenario: str = "",
        start_path: str = "/",
        seed_cart: Optional[Dict[str, int]] = None,
        layout: str = "v1",
        server_kwargs: Optional[Dict[str, Any]] = None,
        require_approval: bool = False,
    ) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.site = site
        self.instruction = instruction
        self.scenario = scenario
        self.start_path = start_path
        self.seed_cart = dict(seed_cart or {})
        self.layout = layout
        self.server_kwargs = dict(server_kwargs or {})
        self.require_approval = require_approval
        self.status = "created"
        self.paused = False
        self.approved = False
        self.events: List[Dict[str, Any]] = []
        self.steps: List[Dict[str, Any]] = []
        self.state: Dict[str, Any] = {}
        self.page = ""
        self.screenshot_b64 = ""
        self.frames = 0
        self.result: Dict[str, Any] = {}
        self.observation: Dict[str, Any] = {}
        self.error = ""
        self.created_at = datetime.now().isoformat(timespec="seconds")
        self.started = 0.0
        self.finished = 0.0
        self._env: Optional[BrowserEnv] = None
        self._server: Optional[LocalShopServer] = None
        self._task: Optional[asyncio.Task] = None
        self._pending: Dict[str, Any] = {}
        self.audit_dir = AUDIT_ROOT / self.id
        self.audit_dir.mkdir(parents=True, exist_ok=True)

    def event(self, kind: str, **payload: Any) -> None:
        record = {"ts": datetime.now().isoformat(timespec="seconds"), "kind": kind, **payload}
        self.events.append(record)
        with (self.audit_dir / "events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    @property
    def elapsed(self) -> float:
        if not self.started:
            return 0.0
        return round((self.finished or time.time()) - self.started, 2)

    def snapshot(self, full: bool = True) -> Dict[str, Any]:
        data = {
            "id": self.id,
            "site": self.site,
            "scenario": self.scenario,
            "instruction": self.instruction,
            "layout": self.layout,
            "status": self.status,
            "paused": self.paused,
            "approved": self.approved,
            "require_approval": self.require_approval,
            "created_at": self.created_at,
            "elapsed": self.elapsed,
            "page": self.page,
            "steps": self.steps if full else len(self.steps),
            "state": self.state,
            "result": self.result,
            "error": self.error,
        }
        if full:
            data["events"] = self.events[-80:]
            data["screenshot"] = self.screenshot_b64
            data["frames"] = self.frames
            data["observation"] = self.observation
        return data


class SessionManager:
    def __init__(self) -> None:
        self.sessions: Dict[str, Session] = {}

    def create(
        self,
        site: str,
        instruction: str,
        scenario_id: Optional[str] = None,
        require_approval: bool = False,
    ) -> Session:
        if site != "local":
            raise ValueError("Studio drives the real local site only")
        scenario = get_scenario(scenario_id)
        if scenario_id and scenario is None:
            raise ValueError(f"unknown scenario: {scenario_id}")
        text = (instruction or (scenario.instruction if scenario else "")).strip()
        if not text:
            raise ValueError("instruction is required")
        if len(text) > MAX_INSTRUCTION:
            raise ValueError(f"instruction exceeds {MAX_INSTRUCTION} characters")
        if sum(1 for s in self.sessions.values() if s.status in ACTIVE) >= MAX_ACTIVE:
            raise StudioBusy(f"at most {MAX_ACTIVE} live sessions")
        self._prune()
        session = Session(
            site,
            text,
            scenario=scenario.id if scenario else "",
            start_path=scenario.start_path if scenario else "/",
            seed_cart=scenario.seed_cart if scenario else None,
            layout=scenario.layout if scenario else "v1",
            server_kwargs=scenario.server_kwargs if scenario else None,
            require_approval=require_approval,
        )
        self.sessions[session.id] = session
        session._task = asyncio.create_task(self._run_local(session))
        return session

    def _prune(self) -> None:
        finished = [s for s in self.sessions.values() if s.status in TERMINAL]
        for stale in finished[: max(0, len(self.sessions) - MAX_SESSIONS + 1)]:
            self.sessions.pop(stale.id, None)

    async def _run_local(self, session: Session) -> None:
        try:
            session.status = "starting"
            session.started = time.time()
            session.event("start", instruction=session.instruction, scenario=session.scenario)
            session._server = LocalShopServer(
                layout=session.layout, **session.server_kwargs
            ).start()
            session._env = BrowserEnv(
                session._server,
                channel=os.environ.get("STEP_RL_BROWSER_CHANNEL", "msedge"),
                headless=True,
                semantic=True,
            )
            session._env.action_hooks.append(
                lambda phase, action, result: self._on_action(session, phase, action, result)
            )
            await session._env.start()
            task = TaskSpec(
                task_id=f"studio_{session.id}",
                level=3,
                goal=session.instruction,
                search_query="",
                targets={},
                start_path=session.start_path,
                seed_cart=session.seed_cart,
            )
            await session._env.reset(task)
            await self._refresh(session, "initial")
            session.status = "running"
            result = await run_task(session._env, session.instruction, None, None)
            steps = result.get("steps", [])
            skill_steps = sum(1 for step in steps if getattr(step, "source", "") == "skill")
            policy_steps = sum(1 for step in steps if getattr(step, "source", "") == "policy")
            session.result = {
                "success": bool(result.get("success")),
                "attempts": len(result.get("attempts", [])),
                "fallback": bool(result.get("fallback", False)),
                "fallback_required": bool(result.get("fallback_required", False)),
                "actions": len(session.steps),
                "skill_steps": skill_steps or (0 if policy_steps else len(session.steps)),
                "policy_steps": policy_steps,
                "prompt_tokens": sum(len(getattr(s, "prompt_ids", []) or []) for s in steps),
                "spec": result.get("spec"),
                "detail": result.get("error", ""),
                "healed_skill": result.get("healed_skill", ""),
            }
            await self._refresh(session, "final")
            session.observation = dict(session._env.observation_metrics)
            session.observation["seconds"] = round(session.observation.get("seconds", 0.0), 3)
            session.status = "success" if session.result["success"] else "failed"
            session.finished = time.time()
            session.event("finish", **{k: v for k, v in session.result.items() if k != "spec"})
            logger.info(
                "studio_finish",
                extra={"extra_fields": {"session": session.id, "status": session.status}},
            )
        except asyncio.CancelledError:
            session.status = "cancelled"
            session.finished = time.time()
            raise
        except Exception as exc:
            session.error = f"{type(exc).__name__}: {exc}"
            session.status = "error"
            session.finished = time.time()
            session.event("error", error=session.error)
            logger.warning(
                "studio_error",
                extra={"extra_fields": {"session": session.id, "error": session.error}},
            )
        finally:
            if session._env is not None:
                await session._env.close()
                session._env = None
            if session._server is not None:
                session._server.stop()
                session._server = None

    async def _on_action(
        self,
        session: Session,
        phase: str,
        action: Dict[str, Any],
        result: Optional[Dict[str, Any]],
    ) -> None:
        env = session._env
        if env is None:
            return
        if phase == "before":
            if session.paused:
                session.status = "paused"
                while session.paused:
                    await asyncio.sleep(0.1)
                session.status = "running"
            name = str(action.get("action", "")).lower()
            label = await env.element_label(action) if name in ("click", "type") else ""
            if (
                session.require_approval
                and not session.approved
                and name == "click"
                and any(word in label for word in APPROVAL_LABELS)
            ):
                session.status = "awaiting_approval"
                session.event("approval_required", target=label)
                await self._refresh(session, "approval")
                while not session.approved:
                    await asyncio.sleep(0.1)
                session.status = "running"
            session._pending = {"label": label, "t0": time.perf_counter()}
            return
        pending = session._pending or {}
        params = action.get("params") or {}
        detail = ""
        if isinstance(params, dict):
            if "text" in params:
                detail = str(params.get("text", ""))[:40]
            elif "url" in params:
                detail = str(params.get("url", ""))[:60]
        step = {
            "index": len(session.steps) + 1,
            "action": str(action.get("action", "")),
            "thought": str(action.get("thought", ""))[:60],
            "target": pending.get("label", ""),
            "detail": detail,
            "ok": bool((result or {}).get("ok")),
            "error": str((result or {}).get("error", ""))[:120],
            "ms": round((time.perf_counter() - pending.get("t0", time.perf_counter())) * 1000),
            "source": "skill",
        }
        session.steps.append(step)
        session._pending = {}
        await self._refresh(session, "")

    async def _refresh(self, session: Session, name: str) -> None:
        env = session._env
        if env is None:
            return
        try:
            png = await env.screenshot()
            session.screenshot_b64 = base64.b64encode(png).decode("ascii")
            session.frames += 1
            if name:
                (session.audit_dir / f"{name}.png").write_bytes(png)
        except Exception as exc:
            session.event("screenshot_error", error=str(exc)[:120])
        state = await env.get_state()
        cart = _cart_view(state.get("cart") or {})
        session.page = env.page_url_path
        session.state = {
            "cart": cart,
            "cart_total": sum(row["subtotal"] for row in cart),
            "order": state.get("order"),
            "orders": len(state.get("orders") or []),
            "promo": state.get("promo"),
        }

    def close(self, session_id: str) -> None:
        session = self.sessions.get(session_id)
        if session is None:
            raise KeyError(session_id)
        if session._task and not session._task.done():
            session._task.cancel()


manager = SessionManager()


def _audit_index(limit: int = 30) -> List[Dict[str, Any]]:
    if not AUDIT_ROOT.is_dir():
        return []
    rows = []
    folders = sorted(AUDIT_ROOT.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    for folder in folders[:limit]:
        log = folder / "events.jsonl"
        if not log.is_file():
            continue
        events = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line]
        start = next((e for e in events if e.get("kind") == "start"), {})
        finish = next((e for e in events if e.get("kind") == "finish"), {})
        rows.append(
            {
                "id": folder.name,
                "ts": start.get("ts", ""),
                "instruction": start.get("instruction", ""),
                "scenario": start.get("scenario", ""),
                "success": finish.get("success"),
                "actions": finish.get("actions"),
                "events": len(events),
                "approval": any(e.get("kind") == "approval_required" for e in events),
                "has_final": (folder / "final.png").is_file(),
            }
        )
    return rows


def _meta() -> Dict[str, Any]:
    return {
        "service": "Step-RL Studio",
        "version": VERSION,
        "browser": os.environ.get("STEP_RL_BROWSER_CHANNEL", "msedge"),
        "runtime": "deterministic skills + verifier (0 LLM)",
        "token_required": bool(os.environ.get("CONSOLE_TOKEN")),
        "limits": {"active": MAX_ACTIVE, "instruction": MAX_INSTRUCTION},
        "products": [
            {"pid": p.pid, "name": p.name, "price": p.price, "stock": p.stock}
            for p in PRODUCTS.values()
        ],
        "promos": [
            {"code": p.code, "label": p.label, "threshold": p.threshold, "discount": p.discount}
            for p in PROMOS.values()
        ],
    }


def create_app() -> FastAPI:
    app = FastAPI(title="Step-RL Studio", version=VERSION)
    if STATIC.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC), name="static")

    def _get(session_id: str) -> Session:
        session = manager.sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="not found")
        return session

    @app.get("/health")
    async def health() -> Dict[str, str]:
        return {"status": "ok", "service": "step-rl-studio", "version": VERSION, "ar": "AR035"}

    @app.get("/api/meta", dependencies=[Depends(require_token)])
    async def meta() -> Dict[str, Any]:
        return _meta()

    @app.get("/api/scenarios", dependencies=[Depends(require_token)])
    async def scenarios() -> List[Dict[str, Any]]:
        return list_scenarios()

    @app.get("/api/skills", dependencies=[Depends(require_token)])
    async def skills() -> Dict[str, Any]:
        return build_skills()

    @app.get("/api/evidence", dependencies=[Depends(require_token)])
    async def evidence() -> Dict[str, Any]:
        return build_evidence()

    @app.get("/api/audit", dependencies=[Depends(require_token)])
    async def audit() -> List[Dict[str, Any]]:
        return _audit_index()

    @app.get("/api/audit/{session_id}/final.png", dependencies=[Depends(require_token)])
    async def audit_frame(session_id: str) -> FileResponse:
        if not _SESSION_ID.match(session_id):
            raise HTTPException(status_code=400, detail="invalid session id")
        path = AUDIT_ROOT / session_id / "final.png"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="not found")
        return FileResponse(path, media_type="image/png")

    @app.post("/api/sessions", dependencies=[Depends(require_token)])
    async def create_session(request: RunRequest) -> Dict[str, Any]:
        try:
            session = manager.create(
                request.site, request.instruction, request.scenario, request.require_approval
            )
        except StudioBusy as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return session.snapshot()

    @app.get("/api/sessions", dependencies=[Depends(require_token)])
    async def list_sessions() -> List[Dict[str, Any]]:
        return [s.snapshot(full=False) for s in reversed(list(manager.sessions.values()))]

    @app.get("/api/sessions/{session_id}", dependencies=[Depends(require_token)])
    async def get_session(session_id: str) -> Dict[str, Any]:
        return _get(session_id).snapshot()

    @app.post("/api/sessions/{session_id}/approve", dependencies=[Depends(require_token)])
    async def approve(session_id: str) -> Dict[str, Any]:
        session = _get(session_id)
        session.approved = True
        session.event("approve")
        return session.snapshot()

    @app.post("/api/sessions/{session_id}/pause", dependencies=[Depends(require_token)])
    async def pause(session_id: str) -> Dict[str, Any]:
        session = _get(session_id)
        if session.status in ACTIVE:
            session.paused = True
            session.event("pause")
        return session.snapshot()

    @app.post("/api/sessions/{session_id}/resume", dependencies=[Depends(require_token)])
    async def resume(session_id: str) -> Dict[str, Any]:
        session = _get(session_id)
        session.paused = False
        session.event("resume")
        return session.snapshot()

    @app.post("/api/sessions/{session_id}/cancel", dependencies=[Depends(require_token)])
    async def cancel(session_id: str) -> Dict[str, Any]:
        session = _get(session_id)
        if session.status in ACTIVE:
            manager.close(session_id)
            session.status = "cancelled"
            session.event("cancel")
        return session.snapshot()

    @app.websocket("/ws/{session_id}")
    async def websocket(websocket: WebSocket, session_id: str) -> None:
        expected = os.environ.get("CONSOLE_TOKEN", "")
        if expected and not hmac.compare_digest(
            websocket.query_params.get("token", ""), expected
        ):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        try:
            while True:
                session = manager.sessions.get(session_id)
                if session is None:
                    await websocket.send_json({"error": "not found"})
                    break
                await websocket.send_json(session.snapshot())
                if session.status in TERMINAL:
                    await asyncio.sleep(0.4)
                    await websocket.send_json(session.snapshot())
                    break
                await asyncio.sleep(0.35)
        except WebSocketDisconnect:
            pass

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        page = STATIC / "index.html"
        return HTMLResponse(page.read_text(encoding="utf-8"))

    return app


app = create_app()
