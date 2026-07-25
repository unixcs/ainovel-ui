from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .config import settings
from .db import init_db, json_dumps, json_loads, new_id, transaction, utcnow
from .engine import engine_manager
from .security import decrypt_text, encrypt_text, issue_token, decode_token, hash_password, verify_password

@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.cors_origin] if settings.cors_origin != "*" else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class LoginRequest(BaseModel):
    username: str
    password: str


class InviteCreateRequest(BaseModel):
    note: str = ""
    expires_in_hours: int = 72
    max_uses: int = 1


class InviteClaimRequest(BaseModel):
    code: str
    username: str
    display_name: str
    password: str


class CredentialPayload(BaseModel):
    provider_alias: str = Field(min_length=1)
    provider_type: str | None = None
    model_name: str = Field(min_length=1)
    reasoning_effort: str = "medium"
    base_url: str | None = None
    api_key: str = Field(min_length=1)


class WorkCreateRequest(BaseModel):
    title: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    style: str = "default"
    target_chapters: int | None = 20
    budget_usd: float | None = None
    advance_mode: str = "auto"


class ActionResponse(BaseModel):
    ok: bool
    message: str


def now_plus_hours(hours: int) -> str:
    return (datetime.now(UTC) + timedelta(hours=hours)).isoformat()


def bearer_token(authorization: Annotated[str | None, Header()] = None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="缺少登录令牌")
    return authorization.split(" ", 1)[1]


def current_user(token: Annotated[str, Depends(bearer_token)]) -> dict[str, Any]:
    try:
        payload = decode_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    with transaction() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=? AND active=1", (payload["sub"],)).fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="账号不可用")
        return dict(row)


def require_admin(user: Annotated[dict[str, Any], Depends(current_user)]) -> dict[str, Any]:
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可操作")
    return user


def row_to_user_view(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "role": row["role"],
        "active": bool(row["active"]),
    }


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "engine_mode": settings.engine_mode,
        "time": utcnow(),
    }


@app.post("/api/auth/login")
def login(payload: LoginRequest) -> dict[str, Any]:
    with transaction() as conn:
        row = conn.execute("SELECT * FROM users WHERE username=? AND active=1", (payload.username,)).fetchone()
        if not row or not verify_password(payload.password, row["password_hash"]):
            raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = issue_token({"sub": row["id"], "role": row["role"]})
    return {"token": token, "user": row_to_user_view(row)}


@app.post("/api/auth/claim", response_model=ActionResponse)
def claim(payload: InviteClaimRequest) -> ActionResponse:
    with transaction() as conn:
        invite = conn.execute("SELECT * FROM invites WHERE code=?", (payload.code.strip(),)).fetchone()
        if not invite:
            raise HTTPException(status_code=404, detail="邀请码不存在")
        if invite["revoked_at"]:
            raise HTTPException(status_code=400, detail="邀请码已作废")
        if invite["expires_at"] and invite["expires_at"] < utcnow():
            raise HTTPException(status_code=400, detail="邀请码已过期")
        if invite["used_count"] >= invite["max_uses"]:
            raise HTTPException(status_code=400, detail="邀请码已用完")
        exists = conn.execute("SELECT 1 FROM users WHERE username=?", (payload.username,)).fetchone()
        if exists:
            raise HTTPException(status_code=400, detail="用户名已存在")
        now = utcnow()
        conn.execute(
            """
            INSERT INTO users (id, username, display_name, password_hash, role, active, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'operator', 1, ?, ?)
            """,
            (new_id("usr"), payload.username, payload.display_name, hash_password(payload.password), now, now),
        )
        conn.execute("UPDATE invites SET used_count=used_count+1 WHERE id=?", (invite["id"],))
    return ActionResponse(ok=True, message="领取账号成功")


@app.get("/api/me")
def me(user: Annotated[dict[str, Any], Depends(current_user)]) -> dict[str, Any]:
    return {"user": row_to_user_view(user)}


@app.get("/api/system/overview")
def system_overview(user: Annotated[dict[str, Any], Depends(current_user)]) -> dict[str, Any]:
    with transaction() as conn:
        active_runs = conn.execute(
            "SELECT COUNT(*) AS total FROM works WHERE status IN ('starting', 'running')"
        ).fetchone()["total"]
        active_by_user = conn.execute(
            "SELECT COUNT(*) AS total FROM works WHERE user_id=? AND status IN ('starting', 'running')",
            (user["id"],),
        ).fetchone()["total"]
        invites = conn.execute("SELECT COUNT(*) AS total FROM invites WHERE revoked_at IS NULL").fetchone()["total"]
        works = conn.execute("SELECT COUNT(*) AS total FROM works WHERE user_id=?", (user["id"],)).fetchone()["total"]
    return {
        "active_runs_global": active_runs,
        "active_runs_for_user": active_by_user,
        "invite_count": invites,
        "work_count": works,
        "limits": {
            "per_operator": settings.active_runs_per_operator,
            "global": settings.active_runs_global,
        },
        "engine_mode": settings.engine_mode,
    }


@app.get("/api/invites")
def list_invites(admin: Annotated[dict[str, Any], Depends(require_admin)]) -> dict[str, Any]:
    with transaction() as conn:
        rows = conn.execute("SELECT * FROM invites ORDER BY created_at DESC").fetchall()
    return {
        "items": [
            {
                "id": row["id"],
                "code": row["code"],
                "note": row["note"],
                "expires_at": row["expires_at"],
                "used_count": row["used_count"],
                "max_uses": row["max_uses"],
                "revoked_at": row["revoked_at"],
            }
            for row in rows
        ]
    }


@app.post("/api/invites", response_model=ActionResponse)
def create_invite(payload: InviteCreateRequest, admin: Annotated[dict[str, Any], Depends(require_admin)]) -> ActionResponse:
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO invites (id, code, note, expires_at, max_uses, used_count, revoked_at, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, 0, NULL, ?, ?)
            """,
            (
                new_id("inv"),
                secrets.token_urlsafe(8),
                payload.note,
                now_plus_hours(payload.expires_in_hours),
                payload.max_uses,
                admin["id"],
                utcnow(),
            ),
        )
    return ActionResponse(ok=True, message="邀请码已创建")


@app.post("/api/invites/{invite_id}/revoke", response_model=ActionResponse)
def revoke_invite(invite_id: str, admin: Annotated[dict[str, Any], Depends(require_admin)]) -> ActionResponse:
    with transaction() as conn:
        conn.execute("UPDATE invites SET revoked_at=? WHERE id=?", (utcnow(), invite_id))
    return ActionResponse(ok=True, message="邀请码已作废")


@app.get("/api/credentials/me")
def get_credential(user: Annotated[dict[str, Any], Depends(current_user)]) -> dict[str, Any]:
    with transaction() as conn:
        row = conn.execute("SELECT * FROM credentials WHERE user_id=?", (user["id"],)).fetchone()
        if not row:
            return {"item": None}
    return {
        "item": {
            "provider_alias": row["provider_alias"],
            "provider_type": row["provider_type"],
            "model_name": row["model_name"],
            "reasoning_effort": row["reasoning_effort"],
            "base_url": row["base_url"],
            "masked_api_key": row["masked_api_key"],
            "updated_at": row["updated_at"],
        }
    }


@app.put("/api/credentials/me", response_model=ActionResponse)
def save_credential(payload: CredentialPayload, user: Annotated[dict[str, Any], Depends(current_user)]) -> ActionResponse:
    masked = f"{payload.api_key[:6]}***{payload.api_key[-4:]}" if len(payload.api_key) >= 10 else "***已保存***"
    with transaction() as conn:
        existing = conn.execute("SELECT id FROM credentials WHERE user_id=?", (user["id"],)).fetchone()
        params = (
            payload.provider_alias,
            payload.provider_type,
            payload.model_name,
            payload.reasoning_effort,
            payload.base_url,
            encrypt_text(payload.api_key),
            masked,
            utcnow(),
            user["id"],
        )
        if existing:
            conn.execute(
                """
                UPDATE credentials SET provider_alias=?, provider_type=?, model_name=?, reasoning_effort=?, base_url=?,
                api_key_encrypted=?, masked_api_key=?, updated_at=? WHERE user_id=?
                """,
                params,
            )
        else:
            conn.execute(
                """
                INSERT INTO credentials (id, user_id, provider_alias, provider_type, model_name, reasoning_effort, base_url,
                api_key_encrypted, masked_api_key, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id("cred"),
                    user["id"],
                    payload.provider_alias,
                    payload.provider_type,
                    payload.model_name,
                    payload.reasoning_effort,
                    payload.base_url,
                    encrypt_text(payload.api_key),
                    masked,
                    utcnow(),
                ),
            )
    return ActionResponse(ok=True, message="模型凭证已保存")


@app.post("/api/credentials/test")
def test_credential(payload: CredentialPayload, user: Annotated[dict[str, Any], Depends(current_user)]) -> dict[str, Any]:
    result = {
        "ok": True,
        "message": "字段校验通过",
        "engine_mode": settings.engine_mode,
    }
    if payload.base_url:
        try:
            with httpx.Client(timeout=5.0, follow_redirects=True) as client:
                response = client.get(payload.base_url)
            result["base_url_status"] = response.status_code
        except Exception as exc:
            result["ok"] = False
            result["message"] = f"Base URL 不可达：{exc}"
    return result


@app.get("/api/works")
def list_works(user: Annotated[dict[str, Any], Depends(current_user)]) -> dict[str, Any]:
    with transaction() as conn:
        rows = conn.execute("SELECT * FROM works WHERE user_id=? ORDER BY created_at DESC", (user["id"],)).fetchall()
    return {
        "items": [
            {
                "id": row["id"],
                "title": row["title"],
                "style": row["style"],
                "status": row["status"],
                "current_phase": row["current_phase"],
                "current_flow": row["current_flow"],
                "completed_chapters": row["completed_chapters"],
                "target_chapters": row["target_chapters"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]
    }


@app.post("/api/works", response_model=ActionResponse)
def create_work(payload: WorkCreateRequest, user: Annotated[dict[str, Any], Depends(current_user)]) -> ActionResponse:
    now = utcnow()
    work_id = new_id("wrk")
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO works (id, user_id, title, prompt, style, target_chapters, budget_usd, advance_mode, status,
            current_phase, current_flow, completed_chapters, last_error, active_run_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'idle', '未开始', 'idle', 0, NULL, NULL, ?, ?)
            """,
            (work_id, user["id"], payload.title, payload.prompt, payload.style, payload.target_chapters, payload.budget_usd, payload.advance_mode, now, now),
        )
    work_dir = settings.works_dir / work_id
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "README.txt").write_text(
        f"作品：{payload.title}\n快速开始：{payload.prompt}\n模式：{payload.advance_mode}\n",
        encoding="utf-8",
    )
    return ActionResponse(ok=True, message="作品已创建")


def work_snapshot(work_id: str, user_id: str) -> dict[str, Any]:
    engine_manager.sync_work(work_id)
    with transaction() as conn:
        work = conn.execute("SELECT * FROM works WHERE id=? AND user_id=?", (work_id, user_id)).fetchone()
        if not work:
            raise HTTPException(status_code=404, detail="作品不存在")
        runs = conn.execute("SELECT * FROM runs WHERE work_id=? ORDER BY created_at DESC", (work_id,)).fetchall()
    artifacts = []
    work_dir = settings.works_dir / work_id
    output_root = work_dir / "output" / "novel"
    if output_root.exists():
        for path in sorted(output_root.rglob("*")):
            if path.is_file():
                artifacts.append(
                    {
                        "path": str(path.relative_to(work_dir)),
                        "size": path.stat().st_size,
                        "preview": path.read_text(encoding="utf-8", errors="ignore")[:400],
                    }
                )
    return {
        "work": {
            "id": work["id"],
            "title": work["title"],
            "prompt": work["prompt"],
            "style": work["style"],
            "target_chapters": work["target_chapters"],
            "budget_usd": work["budget_usd"],
            "advance_mode": work["advance_mode"],
            "status": work["status"],
            "current_phase": work["current_phase"],
            "current_flow": work["current_flow"],
            "completed_chapters": work["completed_chapters"],
            "last_error": work["last_error"],
            "active_run_id": work["active_run_id"],
            "updated_at": work["updated_at"],
        },
        "runs": [
            {
                "id": row["id"],
                "status": row["status"],
                "mode": row["mode"],
                "container_name": row["container_name"],
                "started_at": row["started_at"],
                "ended_at": row["ended_at"],
                "meta": json_loads(row["meta_json"], {}),
            }
            for row in runs
        ],
        "artifacts": artifacts,
    }


@app.get("/api/works/{work_id}")
def get_work(work_id: str, user: Annotated[dict[str, Any], Depends(current_user)]) -> dict[str, Any]:
    return work_snapshot(work_id, user["id"])


def enforce_run_limits(conn, user_id: str, work_id: str) -> None:
    current = conn.execute("SELECT * FROM works WHERE id=? AND user_id=?", (work_id, user_id)).fetchone()
    if not current:
        raise HTTPException(status_code=404, detail="作品不存在")
    if current["status"] in {"starting", "running"}:
        raise HTTPException(status_code=400, detail="作品已有活跃创作运行")
    active_for_user = conn.execute(
        "SELECT COUNT(*) AS total FROM works WHERE user_id=? AND status IN ('starting', 'running')", (user_id,)
    ).fetchone()["total"]
    if active_for_user >= settings.active_runs_per_operator:
        raise HTTPException(status_code=400, detail="已达到每位操作者的活跃创作运行上限")
    active_global = conn.execute("SELECT COUNT(*) AS total FROM works WHERE status IN ('starting', 'running')").fetchone()["total"]
    if active_global >= settings.active_runs_global:
        raise HTTPException(status_code=400, detail="全站活跃创作运行已满")


@app.post("/api/works/{work_id}/runs/start", response_model=ActionResponse)
def start_work(work_id: str, user: Annotated[dict[str, Any], Depends(current_user)]) -> ActionResponse:
    run_id = new_id("run")
    with transaction() as conn:
        enforce_run_limits(conn, user["id"], work_id)
        work = conn.execute("SELECT * FROM works WHERE id=? AND user_id=?", (work_id, user["id"])).fetchone()
        if settings.engine_mode == "ainovel":
            cred = conn.execute("SELECT 1 FROM credentials WHERE user_id=?", (user["id"],)).fetchone()
            if not cred:
                raise HTTPException(status_code=400, detail="请先保存模型凭证")
        now = utcnow()
        conn.execute(
            """
            INSERT INTO runs (id, work_id, user_id, status, mode, container_name, pid, meta_json, started_at, ended_at, created_at, updated_at)
            VALUES (?, ?, ?, 'starting', ?, NULL, NULL, '{}', NULL, NULL, ?, ?)
            """,
            (run_id, work_id, user["id"], settings.engine_mode, now, now),
        )
        conn.execute(
            "UPDATE works SET status='starting', current_phase='启动中', current_flow='booting', active_run_id=?, last_error=NULL, updated_at=? WHERE id=?",
            (run_id, now, work_id),
        )
        prompt = work["prompt"]
    try:
        engine_manager.start(work_id, run_id, prompt, resume=False)
    except Exception as exc:
        with transaction() as conn:
            conn.execute("UPDATE runs SET status='failed', ended_at=?, updated_at=?, meta_json=? WHERE id=?", (utcnow(), utcnow(), json_dumps({"error": str(exc)}), run_id))
            conn.execute("UPDATE works SET status='failed', last_error=?, active_run_id=NULL, updated_at=? WHERE id=?", (str(exc), utcnow(), work_id))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ActionResponse(ok=True, message="创作运行已启动")


@app.post("/api/works/{work_id}/runs/pause", response_model=ActionResponse)
def pause_work(work_id: str, user: Annotated[dict[str, Any], Depends(current_user)]) -> ActionResponse:
    with transaction() as conn:
        work = conn.execute("SELECT * FROM works WHERE id=? AND user_id=?", (work_id, user["id"])).fetchone()
        if not work or not work["active_run_id"]:
            raise HTTPException(status_code=400, detail="当前没有可暂停的活跃运行")
        run_id = work["active_run_id"]
    engine_manager.pause(run_id)
    return ActionResponse(ok=True, message="暂停请求已发送")


@app.post("/api/works/{work_id}/runs/continue", response_model=ActionResponse)
def continue_work(work_id: str, user: Annotated[dict[str, Any], Depends(current_user)]) -> ActionResponse:
    run_id = new_id("run")
    with transaction() as conn:
        enforce_run_limits(conn, user["id"], work_id)
        work = conn.execute("SELECT * FROM works WHERE id=? AND user_id=?", (work_id, user["id"])).fetchone()
        if settings.engine_mode == "ainovel":
            cred = conn.execute("SELECT 1 FROM credentials WHERE user_id=?", (user["id"],)).fetchone()
            if not cred:
                raise HTTPException(status_code=400, detail="请先保存模型凭证")
        now = utcnow()
        conn.execute(
            "INSERT INTO runs (id, work_id, user_id, status, mode, container_name, pid, meta_json, started_at, ended_at, created_at, updated_at) VALUES (?, ?, ?, 'starting', ?, NULL, NULL, '{}', NULL, NULL, ?, ?)",
            (run_id, work_id, user["id"], settings.engine_mode, now, now),
        )
        conn.execute(
            "UPDATE works SET status='starting', current_phase='启动中', current_flow='booting', active_run_id=?, last_error=NULL, updated_at=? WHERE id=?",
            (run_id, now, work_id),
        )
        prompt = work["prompt"]
    try:
        engine_manager.start(work_id, run_id, prompt, resume=True)
    except Exception as exc:
        with transaction() as conn:
            conn.execute("UPDATE runs SET status='failed', ended_at=?, updated_at=?, meta_json=? WHERE id=?", (utcnow(), utcnow(), json_dumps({"error": str(exc)}), run_id))
            conn.execute("UPDATE works SET status='failed', last_error=?, active_run_id=NULL, updated_at=? WHERE id=?", (str(exc), utcnow(), work_id))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ActionResponse(ok=True, message="继续创作已启动")
