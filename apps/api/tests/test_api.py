from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

os.environ["XIAOBAI_DATA_DIR"] = tempfile.mkdtemp(prefix="xiaobai-api-test-")
os.environ["XIAOBAI_DB_PATH"] = str(Path(os.environ["XIAOBAI_DATA_DIR"]) / "test.db")
os.environ["XIAOBAI_ENGINE_MODE"] = "mock"
os.environ["XIAOBAI_SECRET_KEY"] = "test-secret-key"
os.environ["XIAOBAI_BOOTSTRAP_ADMIN_USERNAME"] = "admin"
os.environ["XIAOBAI_BOOTSTRAP_ADMIN_PASSWORD"] = "Admin123!"

from fastapi.testclient import TestClient

from app.db import init_db
from app.main import app

init_db()
client = TestClient(app)


def auth_header(username: str, password: str) -> dict[str, str]:
    token = client.post("/api/auth/login", json={"username": username, "password": password}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_bootstrap_admin_login_and_invite_claim_and_run_flow() -> None:
    health = client.get("/api/health")
    assert health.status_code == 200

    admin_headers = auth_header("admin", "Admin123!")
    create_invite = client.post("/api/invites", json={"note": "smoke", "expires_in_hours": 24, "max_uses": 1}, headers=admin_headers)
    assert create_invite.status_code == 200

    invites = client.get("/api/invites", headers=admin_headers).json()["items"]
    assert invites
    code = invites[0]["code"]

    claim = client.post(
        "/api/auth/claim",
        json={"code": code, "username": "writer1", "display_name": "Writer One", "password": "Writer123!"},
    )
    assert claim.status_code == 200

    user_headers = auth_header("writer1", "Writer123!")
    save_cred = client.put(
        "/api/credentials/me",
        json={
            "provider_alias": "openai",
            "provider_type": "openai",
            "model_name": "gpt-5.4-mini",
            "reasoning_effort": "medium",
            "base_url": "https://example.com",
            "api_key": "sk-test-1234567890",
        },
        headers=user_headers,
    )
    assert save_cred.status_code == 200

    work = client.post(
        "/api/works",
        json={
            "title": "测试作品",
            "prompt": "写一本轻松热血的修仙小说",
            "style": "fantasy",
            "target_chapters": 12,
            "advance_mode": "auto",
        },
        headers=user_headers,
    )
    assert work.status_code == 200

    items = client.get("/api/works", headers=user_headers).json()["items"]
    assert len(items) == 1
    work_id = items[0]["id"]

    started = client.post(f"/api/works/{work_id}/runs/start", headers=user_headers)
    assert started.status_code == 200

    deadline = time.time() + 8
    detail = None
    while time.time() < deadline:
        detail = client.get(f"/api/works/{work_id}", headers=user_headers)
        assert detail.status_code == 200
        if detail.json()["work"]["status"] == "completed":
            break
        time.sleep(0.5)
    assert detail is not None
    payload = detail.json()
    assert payload["work"]["status"] == "completed"
    assert payload["work"]["completed_chapters"] >= 3
    assert any(item["path"].endswith("outline.md") for item in payload["artifacts"])
