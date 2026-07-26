from __future__ import annotations

import os
import shutil
import tempfile
import time as real_time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ["XIAOBAI_DATA_DIR"] = tempfile.mkdtemp(prefix="xiaobai-api-test-")
os.environ["XIAOBAI_DB_PATH"] = str(Path(os.environ["XIAOBAI_DATA_DIR"]) / "test.db")
os.environ["XIAOBAI_ENGINE_MODE"] = "mock"
os.environ["XIAOBAI_SECRET_KEY"] = "test-secret-key"
os.environ["XIAOBAI_BOOTSTRAP_ADMIN_USERNAME"] = "admin"
os.environ["XIAOBAI_BOOTSTRAP_ADMIN_PASSWORD"] = "Admin123!"

from app.config import Settings, settings
from app.content import chapter_title_from_markdown
from app.db import init_db, json_loads, new_id, transaction, utcnow
import app.engine as engine_module
from app.main import app

ORIGINAL_SLEEP = real_time.sleep


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


def login(client: TestClient, username: str, password: str) -> dict:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def auth_header_from_token(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def auth_header(client: TestClient, username: str, password: str) -> dict[str, str]:
    return auth_header_from_token(login(client, username, password)["token"])


def change_password(client: TestClient, token: str, current_password: str, new_password: str) -> dict[str, str]:
    headers = auth_header_from_token(token)
    response = client.post(
        "/api/users/me/password",
        json={"current_password": current_password, "new_password": new_password},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {login(client, login_user(headers, client), new_password)['token']}"}


def login_user(headers: dict[str, str], client: TestClient) -> str:
    me = client.get("/api/me", headers=headers)
    assert me.status_code == 200, me.text
    return me.json()["user"]["username"]


def bootstrap_admin_headers(client: TestClient) -> dict[str, str]:
    payload = login(client, "admin", "Admin123!")
    assert payload["user"]["must_change_password"] is True
    blocked = client.get("/api/invites", headers=auth_header_from_token(payload["token"]))
    assert blocked.status_code == 403
    response = client.post(
        "/api/users/me/password",
        json={"current_password": "Admin123!", "new_password": "Admin1234!"},
        headers=auth_header_from_token(payload["token"]),
    )
    assert response.status_code == 200, response.text
    return auth_header(client, "admin", "Admin1234!")


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


def test_bootstrap_admin_must_change_password_and_can_manage_invites(client: TestClient) -> None:
    admin_headers = bootstrap_admin_headers(client)
    presets = client.get("/api/testing/connection-presets", headers=admin_headers)
    assert presets.status_code == 200
    assert presets.json()
    assert all("api_key" not in item for item in presets.json())
    assert all(item["model_name"] != "sensenova-u1-fast" for item in presets.json())
    created = client.post(
        "/api/invites",
        json={"note": "boot", "expires_in_hours": 24, "max_uses": 1},
        headers=admin_headers,
    )
    assert created.status_code == 200


def test_happy_path_credentials_chapters_download_and_password_change(client: TestClient) -> None:
    admin_headers = bootstrap_admin_headers(client)
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
    work_id = works[0]["id"]

    started = client.post(f"/api/works/{work_id}/runs/start", headers=user_headers)
    assert started.status_code == 200, started.text

    payload = wait_for_terminal_status(client, user_headers, work_id)
    assert payload["work"]["status"] == "completed"
    assert payload["chapters"]
    chapter_id = payload["chapters"][0]["id"]

    chapter_detail = client.get(f"/api/works/{work_id}/chapters/{chapter_id}", headers=user_headers)
    assert chapter_detail.status_code == 200, chapter_detail.text
    detail = chapter_detail.json()
    assert detail["cleaned_text"].startswith("第")
    assert "# 第" in detail["raw_markdown"]

    txt = client.get(f"/api/works/{work_id}/chapters/{chapter_id}/download.txt", headers=user_headers)
    assert txt.status_code == 200
    assert txt.headers["content-type"].startswith("text/plain")
    assert "# 第" not in txt.text

    all_txt = client.get(f"/api/works/{work_id}/download/all.txt", headers=user_headers)
    assert all_txt.status_code == 200
    assert "# 第" not in all_txt.text
    assert "测试作品" in all_txt.text

    pwd_change = client.post(
        "/api/users/me/password",
        json={"current_password": "Writer123!", "new_password": "Writer1234!"},
        headers=user_headers,
    )
    assert pwd_change.status_code == 200, pwd_change.text
    relogin = login(client, "writer1", "Writer1234!")
    assert relogin["user"]["must_change_password"] is False


def test_access_control_invite_reuse_and_revoke(client: TestClient) -> None:
    admin_headers = bootstrap_admin_headers(client)
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
    admin_headers = bootstrap_admin_headers(client)
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
    admin_headers = bootstrap_admin_headers(client)
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
    admin_headers = bootstrap_admin_headers(client)
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


def test_ainovel_mode_workspace_path_and_connection_status(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    admin_headers = bootstrap_admin_headers(client)
    user_headers = create_operator(client, admin_headers, "writer7")
    work = client.post(
        "/api/works",
        json={"title": "真引擎路径", "prompt": "测试"},
        headers=user_headers,
    )
    assert work.status_code == 200
    work_id = client.get("/api/works", headers=user_headers).json()["items"][0]["id"]

    monkeypatch.setattr(engine_module.settings, "engine_mode", "ainovel")
    monkeypatch.setattr("app.main.settings.engine_mode", "ainovel")
    output_root = engine_module.engine_manager.output_root(work_id)
    output_root.mkdir(parents=True, exist_ok=True)
    chapter = output_root / "chapters" / "001-第1章.md"
    chapter.parent.mkdir(parents=True, exist_ok=True)
    chapter.write_text("# 第1章\n\nworkspace artifact", encoding="utf-8")

    detail = client.get(f"/api/works/{work_id}", headers=user_headers)
    assert detail.status_code == 200, detail.text
    paths = [item["path"] for item in detail.json()["artifacts"]]
    assert any(path.endswith("workspace/output/novel/chapters/001-第1章.md") for path in paths)

    save_cred = client.put(
        "/api/credentials/me",
        json={
            "provider_alias": "test-openai",
            "provider_type": "openai",
            "model_name": "gpt-5.4-mini",
            "reasoning_effort": "medium",
            "base_url": "https://example.com/v1",
            "api_key": "sk-test-1234567890",
        },
        headers=user_headers,
    )
    assert save_cred.status_code == 200

    monkeypatch.setattr("app.main.probe_model_connection", lambda payload: (True, "连接成功", 200, "pong"))
    tested = client.post(
        "/api/credentials/test",
        json={
            "provider_alias": "test-openai",
            "provider_type": "openai",
            "model_name": "gpt-5.4-mini",
            "reasoning_effort": "medium",
            "base_url": "https://example.com/v1",
            "api_key": "sk-test-1234567890",
        },
        headers=user_headers,
    )
    assert tested.status_code == 200
    cred = client.get("/api/credentials/me", headers=user_headers)
    assert cred.json()["item"]["last_test_status"] == "success"



def test_mock_respects_target_and_returns_full_live_chapter(client: TestClient) -> None:
    admin_headers = bootstrap_admin_headers(client)
    user_headers = create_operator(client, admin_headers, "targetone")
    created = client.post(
        "/api/works",
        json={"title": "单章验收", "prompt": "写一个完整开篇", "target_chapters": 1},
        headers=user_headers,
    )
    assert created.status_code == 200, created.text
    work_id = client.get("/api/works", headers=user_headers).json()["items"][0]["id"]
    started = client.post(f"/api/works/{work_id}/runs/start", headers=user_headers)
    assert started.status_code == 200
    assert "模拟" in started.json()["message"]

    payload = wait_for_terminal_status(client, user_headers, work_id)
    assert payload["work"]["completed_chapters"] == 1
    assert len(payload["chapters"]) == 1
    summary = payload["chapters"][0]
    assert summary["character_count"] > 100
    assert summary["paragraph_count"] >= 5

    chapter_url = f"/api/works/{work_id}/chapters/{summary['id']}"
    first = client.get(chapter_url, headers=user_headers)
    assert first.status_code == 200
    chapter_path = engine_module.engine_manager.output_root(work_id) / "chapters" / summary["filename"]
    chapter_path.write_text(chapter_path.read_text(encoding="utf-8") + "\n\n这是实时追加的完整段落。", encoding="utf-8")
    second = client.get(chapter_url, headers=user_headers)
    assert second.status_code == 200
    assert "实时追加" in second.json()["cleaned_text"]
    assert second.json()["size"] > first.json()["size"]


def test_empty_export_and_unsaved_connection_result_fail_closed(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    admin_headers = bootstrap_admin_headers(client)
    user_headers = create_operator(client, admin_headers, "failclosed")
    client.post(
        "/api/works",
        json={"title": "空作品", "prompt": "尚未运行", "target_chapters": 1},
        headers=user_headers,
    )
    work_id = client.get("/api/works", headers=user_headers).json()["items"][0]["id"]
    empty_export = client.get(f"/api/works/{work_id}/download/all.txt", headers=user_headers)
    assert empty_export.status_code == 404
    assert "暂无" in empty_export.text

    saved_payload = {
        "provider_alias": "saved",
        "provider_type": "openai",
        "model_name": "saved-model",
        "reasoning_effort": "medium",
        "base_url": "https://saved.example/v1",
        "api_key": "sk-saved-123456",
    }
    assert client.put("/api/credentials/me", json=saved_payload, headers=user_headers).status_code == 200
    monkeypatch.setattr("app.main.probe_model_connection", lambda payload: (True, "连接成功", 200, "pong"))
    other_payload = {**saved_payload, "model_name": "different-model"}
    tested = client.post("/api/credentials/test", json=other_payload, headers=user_headers)
    assert tested.status_code == 200
    assert "尚未保存" in tested.json()["message"]
    stored = client.get("/api/credentials/me", headers=user_headers).json()["item"]
    assert stored["last_test_status"] is None

    monkeypatch.setattr(engine_module.settings, "engine_mode", "ainovel")
    monkeypatch.setattr("app.main.settings.engine_mode", "ainovel")
    blocked = client.post(f"/api/works/{work_id}/runs/start", headers=user_headers)
    assert blocked.status_code == 400
    assert "连接测试" in blocked.text


class StubThread:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.started = False

    def start(self) -> None:
        self.started = True


class FakeContainers:
    def __init__(self, container=None):
        self.container = container
        self.run_calls: list[dict] = []

    def run(self, *args, **kwargs):
        self.run_calls.append({"args": args, "kwargs": kwargs})
        return self.container

    def get(self, name: str):
        if self.container is None:
            raise engine_module.NotFound("missing")
        self.container.requested_name = name
        return self.container


class FakeDocker:
    def __init__(self, container=None):
        self.containers = FakeContainers(container)


class FakeContainer:
    def __init__(self, *, fail_stop=False, fail_kill=False, fail_remove=False):
        self.attrs = {"State": {"Status": "running", "ExitCode": 0}}
        self.fail_stop = fail_stop
        self.fail_kill = fail_kill
        self.fail_remove = fail_remove
        self.stop_calls = 0
        self.kill_calls = 0
        self.remove_calls = 0
        self.requested_name = None

    def reload(self) -> None:
        return None

    def stop(self, timeout=10) -> None:
        self.stop_calls += 1
        if self.fail_stop:
            raise engine_module.DockerException("stop unavailable")
        self.attrs["State"] = {"Status": "exited", "ExitCode": 0}

    def kill(self) -> None:
        self.kill_calls += 1
        if self.fail_kill:
            raise engine_module.DockerException("kill unavailable")
        self.attrs["State"] = {"Status": "exited", "ExitCode": 137}

    def remove(self) -> None:
        self.remove_calls += 1
        if self.fail_remove:
            raise engine_module.DockerException("remove unavailable")

    def logs(self, tail=80) -> bytes:
        return b"fake logs"


def insert_active_run(work_id: str, user_id: str, *, container_name: str | None = "xiaobai-test") -> str:
    run_id = new_id("run")
    now = utcnow()
    with transaction() as conn:
        conn.execute(
            "INSERT INTO runs (id, work_id, user_id, status, mode, container_name, pid, meta_json, started_at, ended_at, created_at, updated_at) VALUES (?, ?, ?, 'running', 'ainovel', ?, NULL, '{}', ?, NULL, ?, ?)",
            (run_id, work_id, user_id, container_name, now, now, now),
        )
        conn.execute(
            "UPDATE works SET status='running', current_phase='写作', current_flow='writing', active_run_id=?, updated_at=? WHERE id=?",
            (run_id, now, work_id),
        )
    return run_id


def create_real_engine_fixture(client: TestClient, username: str, *, target_chapters: int = 1) -> tuple[dict[str, str], str, str]:
    admin_headers = bootstrap_admin_headers(client)
    user_headers = create_operator(client, admin_headers, username)
    assert client.put(
        "/api/credentials/me",
        json={
            "provider_alias": "test-openai",
            "provider_type": "openai",
            "model_name": "test-model",
            "reasoning_effort": "medium",
            "base_url": "https://example.com/v1",
            "api_key": "sk-private-test-value",
        },
        headers=user_headers,
    ).status_code == 200
    assert client.post(
        "/api/works",
        json={"title": f"真实引擎-{username}", "prompt": "验证真实引擎边界", "target_chapters": target_chapters},
        headers=user_headers,
    ).status_code == 200
    work_id = client.get("/api/works", headers=user_headers).json()["items"][0]["id"]
    user_id = client.get("/api/me", headers=user_headers).json()["user"]["id"]
    return user_headers, user_id, work_id


def test_ainovel_start_is_headless_limited_and_resume_safe(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _, user_id, work_id = create_real_engine_fixture(client, "enginestart")
    monkeypatch.setattr(engine_module.settings, "engine_mode", "ainovel")
    fake_docker = FakeDocker(FakeContainer())
    monkeypatch.setattr(engine_module.engine_manager, "_docker", fake_docker)
    monkeypatch.setattr(engine_module.threading, "Thread", StubThread)

    first_run = insert_active_run(work_id, user_id, container_name=None)
    engine_module.engine_manager._start_ainovel(work_id, first_run, "fresh prompt", resume=False)
    first = fake_docker.containers.run_calls[-1]["kwargs"]
    assert first["command"] == ["--headless", "--prompt", "fresh prompt"]
    assert first["mem_limit"] == settings.ainovel_memory
    assert first["nano_cpus"] == int(settings.ainovel_cpus * 1_000_000_000)
    assert first["pids_limit"] == settings.ainovel_pids_limit
    assert first["labels"]["com.xiaobai.work_id"] == work_id

    config_path = settings.works_dir / work_id / "config" / "config.json"
    assert config_path.exists()
    assert config_path.stat().st_mode & 0o777 == 0o600
    assert config_path.parent.stat().st_mode & 0o777 == 0o700
    assert "sk-private-test-value" in config_path.read_text(encoding="utf-8")

    with transaction() as conn:
        conn.execute("UPDATE runs SET status='paused' WHERE id=?", (first_run,))
        conn.execute("UPDATE works SET status='paused', active_run_id=NULL WHERE id=?", (work_id,))
    resume_run = insert_active_run(work_id, user_id, container_name=None)
    engine_module.engine_manager._start_ainovel(work_id, resume_run, "ignored prompt", resume=True)
    resumed = fake_docker.containers.run_calls[-1]["kwargs"]
    assert resumed["command"] == ["--headless"]
    engine_module.engine_manager._monitors.clear()


def test_ainovel_target_stop_retries_fail_closed_then_completes(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _, user_id, work_id = create_real_engine_fixture(client, "targetstop", target_chapters=1)
    monkeypatch.setattr(engine_module.settings, "engine_mode", "ainovel")
    chapter_dir = engine_module.engine_manager.output_root(work_id) / "chapters"
    chapter_dir.mkdir(parents=True, exist_ok=True)
    (chapter_dir / "001-第1章.md").write_text("# 第1章\n\n完整正文。", encoding="utf-8")
    run_id = insert_active_run(work_id, user_id)
    container = FakeContainer(fail_stop=True, fail_kill=True)
    monkeypatch.setattr(engine_module.engine_manager, "_docker", FakeDocker(container))

    engine_module.engine_manager.sync_work(work_id)
    with transaction() as conn:
        run = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        work = conn.execute("SELECT * FROM works WHERE id=?", (work_id,)).fetchone()
    assert run["status"] == "running"
    assert json_loads(run["meta_json"])["target_stop_error"]
    assert work["status"] == "running"
    assert work["current_flow"] == "stopping"
    assert work["active_run_id"] == run_id
    assert container.stop_calls == 1 and container.kill_calls == 1
    assert container.remove_calls == 0

    container.fail_stop = False
    container.fail_kill = False
    engine_module.engine_manager.sync_work(work_id)
    with transaction() as conn:
        run = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        work = conn.execute("SELECT * FROM works WHERE id=?", (work_id,)).fetchone()
    assert run["status"] == "completed"
    assert json_loads(run["meta_json"]) == {"stopped_at_target": 1}
    assert work["status"] == "completed"
    assert work["completed_chapters"] == 1
    assert work["active_run_id"] is None
    assert container.remove_calls == 1


def test_chapter_title_falls_back_for_untitled_prose() -> None:
    prose = "清晨七点四十，林维站在档案中心的地面入口。\n\n这是正文。"
    assert chapter_title_from_markdown(prose, "第1章") == "第1章"
    assert chapter_title_from_markdown("第一章 编号不存在\n\n这是正文。", "第1章") == "第一章 编号不存在"
    assert chapter_title_from_markdown("# 第一章 编号不存在\n\n这是正文。", "第1章") == "第一章 编号不存在"



def test_ainovel_host_data_dir_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("XIAOBAI_HOST_DATA_DIR", raising=False)
    with pytest.raises(ValueError, match="XIAOBAI_HOST_DATA_DIR"):
        Settings(engine_mode="ainovel", host_data_dir=None)
    with pytest.raises(ValueError, match="绝对路径"):
        Settings(engine_mode="ainovel", host_data_dir=Path("relative-data"))

    configured = Settings(engine_mode="ainovel", host_data_dir=tmp_path.resolve())
    assert configured.host_data_dir == tmp_path.resolve()
    mock = Settings(engine_mode="mock", data_dir=tmp_path, host_data_dir=None)
    assert mock.host_data_dir == tmp_path

def test_ainovel_recovery_fails_stale_runs_when_docker_is_unavailable(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _, user_id, work_id = create_real_engine_fixture(client, "recoverfail")
    monkeypatch.setattr(engine_module.settings, "engine_mode", "ainovel")
    run_id = insert_active_run(work_id, user_id)
    monkeypatch.setattr(engine_module.engine_manager, "_docker", None)

    engine_module.engine_manager.recover_active_runs()
    with transaction() as conn:
        run = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        work = conn.execute("SELECT * FROM works WHERE id=?", (work_id,)).fetchone()
    assert run["status"] == "failed"
    assert "Docker" in json_loads(run["meta_json"])["error"]
    assert work["status"] == "failed"
    assert work["active_run_id"] is None
