from __future__ import annotations

import os
import shutil
import tempfile
import time as real_time

ORIGINAL_SLEEP = real_time.sleep
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ["XIAOBAI_DATA_DIR"] = tempfile.mkdtemp(prefix="xiaobai-api-test-")
os.environ["XIAOBAI_DB_PATH"] = str(Path(os.environ["XIAOBAI_DATA_DIR"]) / "test.db")
os.environ["XIAOBAI_ENGINE_MODE"] = "mock"
os.environ["XIAOBAI_SECRET_KEY"] = "test-secret-key"
os.environ["XIAOBAI_BOOTSTRAP_ADMIN_USERNAME"] = "admin"
os.environ["XIAOBAI_BOOTSTRAP_ADMIN_PASSWORD"] = "Admin123!"

from app.config import settings
from app.db import init_db
import app.engine as engine_module
from app.main import app


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch):
    shutil.rmtree(settings.data_dir, ignore_errors=True)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(engine_module.time, "sleep", lambda _: None)
    init_db()
    with TestClient(app) as test_client:
        yield test_client
    for thread, _stop_event in list(engine_module.engine_manager._threads.values()):
        thread.join(timeout=2)
    engine_module.engine_manager._threads.clear()
    shutil.rmtree(settings.data_dir, ignore_errors=True)


def auth_header(client: TestClient, username: str, password: str) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    token = response.json()["token"]
    return {"Authorization": f"Bearer {token}"}


def create_operator(client: TestClient, admin_headers: dict[str, str], username: str) -> dict[str, str]:
    response = client.post(
        "/api/invites",
        json={"note": username, "expires_in_hours": 24, "max_uses": 1},
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    code = client.get("/api/invites", headers=admin_headers).json()["items"][0]["code"]
    claim = client.post(
        "/api/auth/claim",
        json={"code": code, "username": username, "display_name": username.upper(), "password": "Writer123!"},
    )
    assert claim.status_code == 200, claim.text
    return auth_header(client, username, "Writer123!")


def wait_for_terminal_status(client: TestClient, headers: dict[str, str], work_id: str, timeout: float = 5.0) -> dict:
    deadline = real_time.time() + timeout
    while real_time.time() < deadline:
        detail = client.get(f"/api/works/{work_id}", headers=headers)
        assert detail.status_code == 200, detail.text
        payload = detail.json()
        if payload["work"]["status"] in {"completed", "failed", "paused"}:
            return payload
        real_time.sleep(0.05)
    raise AssertionError("work did not reach terminal state in time")


def test_happy_path_admin_invite_claim_credentials_work_and_mock_artifacts(client: TestClient) -> None:
    admin_headers = auth_header(client, "admin", "Admin123!")
    user_headers = create_operator(client, admin_headers, "writer1")

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
    assert save_cred.status_code == 200, save_cred.text

    cred_view = client.get("/api/credentials/me", headers=user_headers)
    assert cred_view.status_code == 200
    assert cred_view.json()["item"]["masked_api_key"].startswith("sk-tes")
    assert "1234567890" not in cred_view.text

    create_work = client.post(
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
    assert create_work.status_code == 200, create_work.text

    works = client.get("/api/works", headers=user_headers).json()["items"]
    assert len(works) == 1
    work_id = works[0]["id"]

    started = client.post(f"/api/works/{work_id}/runs/start", headers=user_headers)
    assert started.status_code == 200, started.text

    payload = wait_for_terminal_status(client, user_headers, work_id)
    assert payload["work"]["status"] == "completed"
    assert payload["work"]["completed_chapters"] >= 3
    assert any(item["path"].endswith("outline.md") for item in payload["artifacts"])
    assert any("chapters/" in item["path"] for item in payload["artifacts"])


def test_access_control_invite_reuse_and_revoke(client: TestClient) -> None:
    admin_headers = auth_header(client, "admin", "Admin123!")
    created = client.post(
        "/api/invites",
        json={"note": "revoke-me", "expires_in_hours": 24, "max_uses": 1},
        headers=admin_headers,
    )
    assert created.status_code == 200
    invite = client.get("/api/invites", headers=admin_headers).json()["items"][0]

    revoked = client.post(f"/api/invites/{invite['id']}/revoke", headers=admin_headers)
    assert revoked.status_code == 200

    claim = client.post(
        "/api/auth/claim",
        json={"code": invite["code"], "username": "writer2", "display_name": "Writer 2", "password": "Writer123!"},
    )
    assert claim.status_code == 400
    assert "作废" in claim.text

    active = client.post(
        "/api/invites",
        json={"note": "single-use", "expires_in_hours": 24, "max_uses": 1},
        headers=admin_headers,
    )
    assert active.status_code == 200
    code = client.get("/api/invites", headers=admin_headers).json()["items"][0]["code"]
    claim_ok = client.post(
        "/api/auth/claim",
        json={"code": code, "username": "writer3", "display_name": "Writer 3", "password": "Writer123!"},
    )
    assert claim_ok.status_code == 200
    claim_again = client.post(
        "/api/auth/claim",
        json={"code": code, "username": "writer4", "display_name": "Writer 4", "password": "Writer123!"},
    )
    assert claim_again.status_code == 400
    assert "用完" in claim_again.text

    operator_headers = auth_header(client, "writer3", "Writer123!")
    forbidden = client.get("/api/invites", headers=operator_headers)
    assert forbidden.status_code == 403


def test_validation_rejects_bad_payloads(client: TestClient) -> None:
    admin_headers = auth_header(client, "admin", "Admin123!")
    bad_invite = client.post(
        "/api/invites",
        json={"note": "x", "expires_in_hours": 0, "max_uses": 0},
        headers=admin_headers,
    )
    assert bad_invite.status_code == 422

    user_headers = create_operator(client, admin_headers, "writer5")
    bad_work = client.post(
        "/api/works",
        json={
            "title": "bad",
            "prompt": "bad",
            "target_chapters": -1,
            "budget_usd": -5,
            "advance_mode": "bad-mode",
        },
        headers=user_headers,
    )
    assert bad_work.status_code == 422

    bad_cred = client.put(
        "/api/credentials/me",
        json={
            "provider_alias": "openai",
            "provider_type": "openai",
            "model_name": "gpt-5.4-mini",
            "reasoning_effort": "wrong",
            "base_url": "ftp://example.com",
            "api_key": "abc",
        },
        headers=user_headers,
    )
    assert bad_cred.status_code == 422


def test_run_state_guards_reject_invalid_transitions(client: TestClient) -> None:
    admin_headers = auth_header(client, "admin", "Admin123!")
    user_headers = create_operator(client, admin_headers, "writer6")

    work = client.post(
        "/api/works",
        json={"title": "状态机测试", "prompt": "写一本小说"},
        headers=user_headers,
    )
    assert work.status_code == 200
    work_id = client.get("/api/works", headers=user_headers).json()["items"][0]["id"]

    before_continue = client.post(f"/api/works/{work_id}/runs/continue", headers=user_headers)
    assert before_continue.status_code == 400
    assert "继续创作" in before_continue.text or "暂停" in before_continue.text

    started = client.post(f"/api/works/{work_id}/runs/start", headers=user_headers)
    assert started.status_code == 200
    payload = wait_for_terminal_status(client, user_headers, work_id)
    assert payload["work"]["status"] == "completed"

    start_again = client.post(f"/api/works/{work_id}/runs/start", headers=user_headers)
    assert start_again.status_code == 400

    continue_after_done = client.post(f"/api/works/{work_id}/runs/continue", headers=user_headers)
    assert continue_after_done.status_code == 400

    pause_after_done = client.post(f"/api/works/{work_id}/runs/pause", headers=user_headers)
    assert pause_after_done.status_code == 400


def test_run_limits_per_operator_and_global(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine_module.time, "sleep", lambda _: ORIGINAL_SLEEP(0.2))
    admin_headers = auth_header(client, "admin", "Admin123!")
    user1 = create_operator(client, admin_headers, "limit1")
    user2 = create_operator(client, admin_headers, "limit2")
    user3 = create_operator(client, admin_headers, "limit3")

    for headers, title in [(user1, "u1-a"), (user1, "u1-b"), (user2, "u2-a"), (user3, "u3-a")]:
        response = client.post("/api/works", json={"title": title, "prompt": title}, headers=headers)
        assert response.status_code == 200, response.text

    user1_work_ids = [item["id"] for item in client.get("/api/works", headers=user1).json()["items"]]
    user2_work_id = client.get("/api/works", headers=user2).json()["items"][0]["id"]
    user3_work_id = client.get("/api/works", headers=user3).json()["items"][0]["id"]

    start1 = client.post(f"/api/works/{user1_work_ids[0]}/runs/start", headers=user1)
    assert start1.status_code == 200, start1.text

    second_for_same_user = client.post(f"/api/works/{user1_work_ids[1]}/runs/start", headers=user1)
    assert second_for_same_user.status_code == 400
    assert "上限" in second_for_same_user.text

    start2 = client.post(f"/api/works/{user2_work_id}/runs/start", headers=user2)
    assert start2.status_code == 200, start2.text

    third_global = client.post(f"/api/works/{user3_work_id}/runs/start", headers=user3)
    assert third_global.status_code == 400
    assert "全站" in third_global.text


def test_ainovel_mode_uses_workspace_output_root_for_artifacts(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    admin_headers = auth_header(client, "admin", "Admin123!")
    user_headers = create_operator(client, admin_headers, "writer7")
    work = client.post(
        "/api/works",
        json={"title": "真引擎路径", "prompt": "测试"},
        headers=user_headers,
    )
    assert work.status_code == 200
    work_id = client.get("/api/works", headers=user_headers).json()["items"][0]["id"]

    monkeypatch.setattr(engine_module.settings, "engine_mode", "ainovel")
    monkeypatch.setattr(engine_module.engine_manager, "_docker", None)
    output_root = engine_module.engine_manager.output_root(work_id)
    output_root.mkdir(parents=True, exist_ok=True)
    chapter = output_root / "chapters" / "001-第1章.md"
    chapter.parent.mkdir(parents=True, exist_ok=True)
    chapter.write_text("# 第1章\n\nworkspace artifact", encoding="utf-8")

    detail = client.get(f"/api/works/{work_id}", headers=user_headers)
    assert detail.status_code == 200, detail.text
    paths = [item["path"] for item in detail.json()["artifacts"]]
    assert any(path.endswith("workspace/output/novel/chapters/001-第1章.md") for path in paths)
