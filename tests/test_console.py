"""AR031: Agent Console API and real local session smoke."""

from __future__ import annotations

from fastapi.testclient import TestClient

from step_rl.console.app import app


def test_console_health():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["ar"] == "AR031"


def test_console_rejects_invalid_site_and_empty():
    client = TestClient(app)
    bad = client.post("/api/sessions", json={"site": "jd", "instruction": "x"})
    assert bad.status_code == 400
    empty = client.post("/api/sessions", json={"site": "local", "instruction": " "})
    assert empty.status_code == 400


def test_console_real_local_session():
    import asyncio
    from step_rl.console.app import SessionManager

    async def run():
        manager = SessionManager()
        session = manager.create("local", "买两件无线充电器")
        await session._task
        snapshot = session.snapshot()
        assert snapshot["status"] == "success", snapshot
        assert snapshot["result"]["success"]
        assert snapshot["screenshot"]
        assert any(event["kind"] == "finish" for event in snapshot["events"])

    asyncio.run(run())
