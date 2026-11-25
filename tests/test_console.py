"""AR031 / AR035: Studio API contract and real local sessions on system Edge."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from step_rl.console.app import SessionManager, StudioBusy, app
from step_rl.console.scenarios import SCENARIOS

BROWSER_ERRORS = ("msedge", "browser", "playwright", "executable")


def _skip_if_no_browser(snapshot):
    error = str(snapshot.get("error", "")).lower()
    if snapshot["status"] == "error" and any(key in error for key in BROWSER_ERRORS):
        pytest.skip(f"browser unavailable: {error}")


def test_console_health():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ar"] == "AR035"
    assert body["service"] == "step-rl-studio"


def test_console_rejects_invalid_site_and_empty():
    client = TestClient(app)
    bad = client.post("/api/sessions", json={"site": "jd", "instruction": "x"})
    assert bad.status_code == 400
    empty = client.post("/api/sessions", json={"site": "local", "instruction": " "})
    assert empty.status_code == 400


def test_console_rejects_unknown_scenario_and_long_instruction():
    client = TestClient(app)
    unknown = client.post("/api/sessions", json={"scenario": "nope", "instruction": ""})
    assert unknown.status_code == 400
    assert "unknown scenario" in unknown.json()["detail"]
    long = client.post("/api/sessions", json={"instruction": "买" * 201})
    assert long.status_code == 400


def test_studio_serves_frontend_and_static_assets():
    client = TestClient(app)
    page = client.get("/")
    assert page.status_code == 200
    assert "Step-RL Studio" in page.text
    for asset in ("app.js", "styles.css", "logo.svg"):
        assert client.get(f"/static/{asset}").status_code == 200


def test_scenarios_endpoint_hides_server_internals():
    client = TestClient(app)
    rows = client.get("/api/scenarios").json()
    assert [row["id"] for row in rows] == list(SCENARIOS)
    assert len({row["id"] for row in rows}) == len(rows)
    for row in rows:
        assert "server_kwargs" not in row
        assert row["instruction"] and row["title"] and row["evidence"]
        assert isinstance(row["fixtures"], list)
    stockout = next(row for row in rows if row["id"] == "stockout-fallback")
    assert stockout["fixtures"]


def test_skills_endpoint_lists_compiled_and_memory():
    client = TestClient(app)
    data = client.get("/api/skills").json()
    names = {skill["name"] for skill in data["compiled"]}
    assert {"search", "add_item", "checkout", "cart_to_order"} <= names
    assert {skill["kind"] for skill in data["compiled"]} <= {"compiled", "transaction", "induced"}
    for skill in data["compiled"]:
        assert skill["steps"], skill["name"]
    assert isinstance(data["induced"], list)
    assert data["memory"]["records"] >= 0
    assert isinstance(data["memory"]["pages"], dict)


def test_evidence_endpoint_is_backed_by_result_files():
    client = TestClient(app)
    data = client.get("/api/evidence").json()
    values = {kpi["label"]: kpi["value"] for kpi in data["headline"]}
    assert any("30/30" in value for value in values.values())
    assert all(kpi["source"] for kpi in data["headline"])
    assert len(data["scenarios"]) == 30
    assert data["attempts"]["kept"] + data["attempts"]["archived"] == data["attempts"]["total"]
    assert len(data["milestones"]) >= 6
    for row in data["ablations"]:
        assert 0 <= row["baseline"] <= row["value"] <= 100


def test_meta_endpoint_describes_runtime():
    client = TestClient(app)
    meta = client.get("/api/meta").json()
    assert meta["limits"]["instruction"] == 200
    assert meta["products"] and meta["promos"]
    assert "0 LLM" in meta["runtime"]


def test_audit_frame_validates_session_id():
    client = TestClient(app)
    assert client.get("/api/audit/NOT-AN-ID/final.png").status_code == 400
    assert client.get("/api/audit/0123456789ab/final.png").status_code == 404
    assert isinstance(client.get("/api/audit").json(), list)


def test_unknown_session_returns_404():
    client = TestClient(app)
    assert client.get("/api/sessions/000000000000").status_code == 404
    assert client.post("/api/sessions/000000000000/approve").status_code == 404


def test_active_session_limit(monkeypatch):
    async def idle(self, session):
        session.status = "running"
        await asyncio.sleep(30)

    monkeypatch.setattr(SessionManager, "_run_local", idle)

    async def run():
        manager = SessionManager()
        first = manager.create("local", "买一件iPhone 15")
        second = manager.create("local", "买一件iPhone 15")
        await asyncio.sleep(0)
        with pytest.raises(StudioBusy):
            manager.create("local", "买一件iPhone 15")
        for session in (first, second):
            manager.close(session.id)
        await asyncio.gather(first._task, second._task, return_exceptions=True)

    asyncio.run(run())


def test_console_token_auth(monkeypatch):
    monkeypatch.setenv("CONSOLE_TOKEN", "secret")
    client = TestClient(app)
    assert client.get("/api/sessions").status_code == 401
    assert client.get("/api/scenarios", headers={"X-Console-Token": "wrong"}).status_code == 401
    allowed = client.get("/api/sessions", headers={"X-Console-Token": "secret"})
    assert allowed.status_code == 200
    assert isinstance(allowed.json(), list)


def test_console_real_local_session():
    async def run():
        manager = SessionManager()
        session = manager.create("local", "买两件无线充电器")
        await session._task
        snapshot = session.snapshot()
        _skip_if_no_browser(snapshot)
        assert snapshot["status"] == "success", snapshot
        assert snapshot["result"]["success"]
        assert snapshot["result"]["prompt_tokens"] == 0
        assert snapshot["screenshot"]
        assert snapshot["steps"] and all(step["ok"] for step in snapshot["steps"])
        assert {row["pid"]: row["qty"] for row in snapshot["state"]["cart"]} == {"p3": 2}
        assert not snapshot["state"]["order"], "cart-only instruction must not place an order"
        assert any(event["kind"] == "finish" for event in snapshot["events"])
        assert (session.audit_dir / "final.png").is_file()

    asyncio.run(run())


@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_every_studio_scenario_runs_on_real_browser(scenario):
    async def run():
        manager = SessionManager()
        session = manager.create("local", "", scenario_id=scenario)
        await session._task
        snapshot = session.snapshot()
        _skip_if_no_browser(snapshot)
        assert snapshot["status"] == "success", snapshot
        assert snapshot["state"]["order"], snapshot["state"]
        assert snapshot["page"].startswith("/order/")

    asyncio.run(run())


def test_approval_gate_holds_order_until_approved():
    async def run():
        manager = SessionManager()
        session = manager.create("local", "买两件USB-C数据线并结算", require_approval=True)
        for _ in range(600):
            if session.status in ("awaiting_approval", "error", "failed", "success"):
                break
            await asyncio.sleep(0.1)
        _skip_if_no_browser(session.snapshot())
        assert session.status == "awaiting_approval"
        held = len(session.steps)
        await asyncio.sleep(1.0)
        assert len(session.steps) == held
        assert not session.state.get("order")
        session.approved = True
        await session._task
        assert session.status == "success"
        kinds = [event["kind"] for event in session.events]
        assert "approval_required" in kinds
        assert session.state["order"]

    asyncio.run(run())


def test_pause_freezes_actions_until_resume():
    async def run():
        manager = SessionManager()
        session = manager.create("local", "买一件iPhone 15和两件数据线，完成结算")
        for _ in range(600):
            if session.steps or session.status in ("error", "failed", "success"):
                break
            await asyncio.sleep(0.05)
        _skip_if_no_browser(session.snapshot())
        session.paused = True
        await asyncio.sleep(1.5)
        frozen = len(session.steps)
        assert session.status == "paused"
        await asyncio.sleep(1.0)
        assert len(session.steps) == frozen
        session.paused = False
        await session._task
        assert session.status == "success"
        assert len(session.steps) > frozen

    asyncio.run(run())
