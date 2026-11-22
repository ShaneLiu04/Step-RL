"""FastAPI Agent Console (AR031): live local runs, traces, approval, audit."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from ..edge.browser import BrowserEnv
from ..edge.runtime import run_task
from ..edge.site import LocalShopServer
from ..logging_utils import get_logger

ROOT = Path(__file__).resolve().parent.parent.parent
AUDIT_ROOT = ROOT / "outputs" / "ar031" / "sessions"
logger = get_logger("step_rl.console")


def require_token(
    x_console_token: Optional[str] = Header(default=None),
) -> None:
    expected = os.environ.get("CONSOLE_TOKEN", "")
    if expected and x_console_token != expected:
        raise HTTPException(status_code=401, detail="console token required")


class RunRequest(BaseModel):
    instruction: str
    site: str = "local"


class Session:
    def __init__(self, site: str, instruction: str) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.site = site
        self.instruction = instruction
        self.status = "created"
        self.paused = False
        self.approved = False
        self.events: List[Dict[str, Any]] = []
        self.screenshot_b64 = ""
        self.result: Dict[str, Any] = {}
        self.error = ""
        self._env: Optional[BrowserEnv] = None
        self._server: Optional[LocalShopServer] = None
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self.audit_dir = AUDIT_ROOT / self.id
        self.audit_dir.mkdir(parents=True, exist_ok=True)

    def event(self, kind: str, **payload: Any) -> None:
        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "kind": kind,
            **payload,
        }
        self.events.append(record)
        with (self.audit_dir / "events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def snapshot(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "site": self.site,
            "instruction": self.instruction,
            "status": self.status,
            "paused": self.paused,
            "approved": self.approved,
            "events": self.events[-80:],
            "screenshot": self.screenshot_b64,
            "result": self.result,
            "error": self.error,
        }


class SessionManager:
    def __init__(self) -> None:
        self.sessions: Dict[str, Session] = {}

    def create(self, site: str, instruction: str) -> Session:
        if site != "local":
            raise ValueError("AR031 MVP supports real local site only")
        if not instruction.strip():
            raise ValueError("instruction is required")
        session = Session(site, instruction)
        self.sessions[session.id] = session
        session._task = asyncio.create_task(self._run_local(session))
        return session

    async def _run_local(self, session: Session) -> None:
        try:
            session.status = "starting"
            session.event("start", instruction=session.instruction)
            session._server = LocalShopServer().start()
            session._env = BrowserEnv(
                session._server,
                channel="msedge",
                headless=True,
                semantic=True,
            )
            await session._env.start()
            await self._capture(session, "initial")
            session.status = "running"
            capture = asyncio.create_task(self._stream(session))
            result = await run_task(
                session._env, session.instruction, None, None
            )
            session._stop.set()
            await capture
            session.result = {
                "success": bool(result.get("success")),
                "attempts": len(result.get("attempts", [])),
                "fallback": bool(result.get("fallback", False)),
                "steps": len(result.get("steps", [])),
                "spec": result.get("spec"),
            }
            session.status = "success" if session.result["success"] else "failed"
            session.event("finish", **session.result)
            logger.info("console_finish", extra={"extra_fields": {"session": session.id, "status": session.status}})
            await self._capture(session, "final")
        except Exception as exc:
            session.error = f"{type(exc).__name__}: {exc}"
            session.status = "error"
            session.event("error", error=session.error)
            logger.warning("console_error", extra={"extra_fields": {"session": session.id, "error": session.error}})
        finally:
            session._stop.set()
            if session._env is not None:
                await session._env.close()
                session._env = None
            if session._server is not None:
                session._server.stop()
                session._server = None

    async def _capture(self, session: Session, name: str) -> None:
        if session._env is None:
            return
        try:
            png = await session._env.screenshot()
            session.screenshot_b64 = base64.b64encode(png).decode("ascii")
            (session.audit_dir / f"{name}.png").write_bytes(png)
            session.event("screenshot", name=name)
        except Exception as exc:
            session.event("screenshot_error", error=str(exc))

    async def _stream(self, session: Session) -> None:
        while not session._stop.is_set():
            await self._capture(session, "stream")
            await asyncio.sleep(0.7)

    def close(self, session_id: str) -> None:
        session = self.sessions.get(session_id)
        if session is None:
            raise KeyError(session_id)
        session._stop.set()
        if session._task:
            session._task.cancel()


manager = SessionManager()


def create_app() -> FastAPI:
    app = FastAPI(title="Step-RL Agent Console", version="AR031")

    @app.get("/health")
    async def health() -> Dict[str, str]:
        return {"status": "ok", "ar": "AR031"}

    @app.post("/api/sessions", dependencies=[Depends(require_token)])
    async def create_session(request: RunRequest) -> Dict[str, Any]:
        try:
            session = manager.create(request.site, request.instruction)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return session.snapshot()

    @app.get("/api/sessions", dependencies=[Depends(require_token)])
    async def list_sessions() -> List[Dict[str, Any]]:
        return [s.snapshot() for s in manager.sessions.values()]

    @app.get("/api/sessions/{session_id}", dependencies=[Depends(require_token)])
    async def get_session(session_id: str) -> Dict[str, Any]:
        session = manager.sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="not found")
        return session.snapshot()

    @app.post("/api/sessions/{session_id}/approve", dependencies=[Depends(require_token)])
    async def approve(session_id: str) -> Dict[str, Any]:
        session = manager.sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="not found")
        session.approved = True
        session.event("approve")
        return session.snapshot()

    @app.post("/api/sessions/{session_id}/pause", dependencies=[Depends(require_token)])
    async def pause(session_id: str) -> Dict[str, Any]:
        session = manager.sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="not found")
        session.paused = True
        session.event("pause")
        return session.snapshot()

    @app.post("/api/sessions/{session_id}/resume", dependencies=[Depends(require_token)])
    async def resume(session_id: str) -> Dict[str, Any]:
        session = manager.sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="not found")
        session.paused = False
        session.event("resume")
        return session.snapshot()

    @app.post("/api/sessions/{session_id}/cancel", dependencies=[Depends(require_token)])
    async def cancel(session_id: str) -> Dict[str, Any]:
        try:
            manager.close(session_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="not found")
        session = manager.sessions[session_id]
        session.status = "cancelled"
        session.event("cancel")
        return session.snapshot()

    @app.websocket("/ws/{session_id}")
    async def websocket(websocket: WebSocket, session_id: str) -> None:
        expected = os.environ.get("CONSOLE_TOKEN", "")
        if expected and websocket.query_params.get("token") != expected:
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
                if session.status in ("success", "failed", "error", "cancelled"):
                    await asyncio.sleep(0.5)
                    await websocket.send_json(session.snapshot())
                    break
                await asyncio.sleep(0.7)
        except WebSocketDisconnect:
            pass

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return INDEX_HTML

    return app


app = create_app()

INDEX_HTML = """<!doctype html>
<html lang="zh"><head><meta charset="utf-8"><title>Step-RL Agent Console</title>
<style>
body{font-family:Segoe UI,Arial;margin:0;background:#0b1020;color:#e6edf7}
header{padding:14px 24px;background:#111827;font-weight:600}
main{display:grid;grid-template-columns:420px 1fr;gap:18px;padding:18px}
.card{background:#151c2e;border:1px solid #26324a;border-radius:12px;padding:16px}
input{width:100%;padding:10px;border-radius:8px;border:1px solid #334155;background:#0f172a;color:#e6edf7}
button{margin:6px 6px 0 0;padding:8px 12px;border-radius:8px;border:0;background:#2563eb;color:#fff;cursor:pointer}
button.secondary{background:#475569} button.danger{background:#b91c1c}
#log{height:360px;overflow:auto;font-family:Consolas,monospace;font-size:12px;white-space:pre-wrap}
#screen{width:100%;border-radius:10px;border:1px solid #26324a;background:#000}
.status{color:#93c5fd}
</style></head><body>
<header>Step-RL Agent Console · AR031</header>
<main>
<div class="card">
  <h3>任务</h3>
  <input id="instruction" value="买两件无线充电器" />
  <button onclick="start()">开始真实运行</button>
  <button class="secondary" onclick="act('pause')">暂停</button>
  <button class="secondary" onclick="act('resume')">恢复</button>
  <button class="secondary" onclick="act('approve')">审批</button>
  <button class="danger" onclick="act('cancel')">取消</button>
  <p class="status" id="status">idle</p>
  <h3>事件</h3><div id="log"></div>
</div>
<div class="card">
  <h3>实时画面</h3>
  <img id="screen" alt="real browser screen" />
  <h3>验证器/结果</h3><pre id="result"></pre>
</div>
</main>
<script>
let sid=null, ws=null; const TOKEN=new URLSearchParams(location.search).get('token')||'';
function render(s){
  document.getElementById('status').textContent = s.status + (s.paused?' (paused)':'') + (s.approved?' · approved':'');
  document.getElementById('result').textContent = JSON.stringify(s.result||{}, null, 2) + (s.error?('\n'+s.error):'');
  document.getElementById('log').textContent = (s.events||[]).map(e=>JSON.stringify(e)).join('\n');
  if(s.screenshot) document.getElementById('screen').src='data:image/png;base64,'+s.screenshot;
}
async function start(){
  const r=await fetch('/api/sessions',{method:'POST',headers:{'Content-Type':'application/json','X-Console-Token':TOKEN},body:JSON.stringify({instruction:document.getElementById('instruction').value,site:'local'})});
  const s=await r.json(); sid=s.id; render(s);
  if(ws) ws.close(); ws=new WebSocket('ws://'+location.host+'/ws/'+sid+(TOKEN?('?token='+encodeURIComponent(TOKEN)):'')); ws.onmessage=e=>render(JSON.parse(e.data));
}
async function act(a){ if(!sid) return; const r=await fetch('/api/sessions/'+sid+'/'+a,{method:'POST',headers:{'X-Console-Token':TOKEN}}); render(await r.json()); }
</script></body></html>"""
