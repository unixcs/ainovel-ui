from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from urllib.parse import quote

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field, field_validator

from .config import settings
from .content import list_chapters, load_chapter_by_id, render_all_chapters_txt, render_chapter_txt
from .db import init_db, json_dumps, json_loads, new_id, transaction, utcnow
from .engine import engine_manager
from .security import decode_token, decrypt_text, encrypt_text, hash_password, issue_token, verify_password

STARTABLE_STATUSES = {"idle"}
CONTINUABLE_STATUSES = {"paused", "failed", "quota_stop"}
PAUSABLE_STATUSES = {"starting", "running"}
REASONING_EFFORTS = {"off", "low", "medium", "high", "xhigh", "max"}
PASSWORD_CHANGE_EXEMPT_PATHS = {"/api/me", "/api/users/me/password"}
OPENAI_COMPATIBLE_TYPES = {None, "", "openai", "openrouter", "deepseek", "qwen", "glm", "grok", "mimo"}


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    engine_manager.recover_active_runs()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.cors_origin] if settings.cors_origin != "*" else ["*"],
    allow_credentials=settings.cors_origin != "*",
    allow_methods=["*"],
    allow_headers=["*"],
)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("用户名不能为空")
        return value


class InviteCreateRequest(BaseModel):
    note: str = ""
    expires_in_hours: int = Field(default=72, ge=1, le=24 * 30)
    max_uses: int = Field(default=1, ge=1, le=1000)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str) -> str:
        return value.strip()


class InviteClaimRequest(BaseModel):
    code: str = Field(min_length=1, max_length=128)
    username: str = Field(min_length=3, max_length=64)
    display_name: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("code", "username", "display_name")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("字段不能为空")
        return value


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def strong_new_password(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 8:
            raise ValueError("新密码至少 8 位")
        return value


class CredentialPayload(BaseModel):
    provider_alias: str = Field(min_length=1, max_length=64)
    provider_type: str | None = None
    model_name: str = Field(min_length=1, max_length=128)
    reasoning_effort: Literal["off", "low", "medium", "high", "xhigh", "max"] = "medium"
    base_url: str | None = None
    api_key: str = Field(min_length=6, max_length=512)

    @field_validator("provider_alias", "model_name", "api_key")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("字段不能为空")
        return value

    @field_validator("provider_type", "base_url")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str | None) -> str | None:
        if value and not value.startswith(("http://", "https://")):
            raise ValueError("Base URL 必须以 http:// 或 https:// 开头")
        return value


class WorkCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=128)
    prompt: str = Field(min_length=1, max_length=5000)
    style: str = Field(default="default", min_length=1, max_length=64)
    target_chapters: int | None = Field(default=20, ge=1, le=10000)
    budget_usd: float | None = Field(default=None, gt=0)
    advance_mode: Literal["auto", "review"] = "auto"

    @field_validator("title", "prompt", "style")
    @classmethod
    def normalize_work_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("字段不能为空")
        return value


class ActionResponse(BaseModel):
    ok: bool
    message: str


class UserView(BaseModel):
    id: str
    username: str
    display_name: str
    role: str
    active: bool
    must_change_password: bool


class WorkView(BaseModel):
    id: str
    title: str
    style: str
    status: str
    current_phase: str
    current_flow: str
    completed_chapters: int
    target_chapters: int | None
    updated_at: str


class InviteView(BaseModel):
    id: str
    code: str
    note: str
    expires_at: str | None
    used_count: int
    max_uses: int
    revoked_at: str | None
    created_at: str


class CredentialView(BaseModel):
    provider_alias: str
    provider_type: str | None
    model_name: str
    reasoning_effort: str
    base_url: str | None
    masked_api_key: str
    updated_at: str
    last_test_status: str | None
    last_test_message: str | None
    last_tested_at: str | None


class ChapterSummaryView(BaseModel):
    id: str
    index: int
    title: str
    filename: str
    size: int
    updated_at: str
    character_count: int
    paragraph_count: int


class RunView(BaseModel):
    id: str
    status: str
    mode: str
    container_name: str | None
    started_at: str | None
    ended_at: str | None
    meta: dict[str, Any]


class ArtifactView(BaseModel):
    path: str
    size: int
    preview: str


class CredentialTestResponse(BaseModel):
    ok: bool
    message: str
    engine_mode: str
    base_url_status: int | None = None
    model_reply_preview: str | None = None


class ConnectionPresetView(BaseModel):
    label: str
    provider_alias: str
    provider_type: str
    base_url: str
    model_name: str
    note: str


class HealthView(BaseModel):
    ok: bool
    engine_mode: str
    time: str


class LoginResponse(BaseModel):
    token: str
    user: UserView


class MeView(BaseModel):
    user: UserView


class InviteListView(BaseModel):
    items: list[InviteView]


class CredentialItemView(BaseModel):
    item: CredentialView | None


class WorkListView(BaseModel):
    items: list[WorkView]


class SystemOverviewView(BaseModel):
    active_runs_global: int
    active_runs_for_user: int
    invite_count: int
    work_count: int
    limits: dict[str, int]
    engine_mode: str


class WorkStatusView(BaseModel):
    work: dict[str, Any]
    runs: list[RunView]
    artifacts: list[ArtifactView]
    chapters: list[ChapterSummaryView]


class ChapterDetailView(BaseModel):
    id: str
    index: int
    title: str
    filename: str
    cleaned_text: str
    raw_markdown: str
    size: int
    updated_at: str
    character_count: int
    paragraph_count: int


class ChapterListView(BaseModel):
    items: list[ChapterSummaryView]


TEST_CONNECTION_PRESETS = [
    {
        "label": "SenseNova Flash Lite",
        "provider_alias": "sensenova",
        "provider_type": "openai",
        "base_url": "https://token.sensenova.cn/v1",
        "model_name": "sensenova-6.7-flash-lite",
        "note": "仅填充公开连接参数；API Key 需由操作者自行输入。",
    },
]



def now_plus_hours(hours: int) -> str:
    return (datetime.now(UTC) + timedelta(hours=hours)).isoformat()


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def is_expired(timestamp: str | None) -> bool:
    moment = parse_timestamp(timestamp)
    if not moment:
        return False
    return moment <= datetime.now(UTC)


def bearer_token(authorization: Annotated[str | None, Header()] = None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="缺少登录令牌")
    return authorization.split(" ", 1)[1]


def current_user(request: Request, token: Annotated[str, Depends(bearer_token)]) -> dict[str, Any]:
    try:
        payload = decode_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    with transaction() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=? AND active=1", (payload["sub"],)).fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="账号不可用")
        user = dict(row)
    if bool(user.get("must_change_password")) and request.url.path not in PASSWORD_CHANGE_EXEMPT_PATHS:
        raise HTTPException(status_code=403, detail="请先完成首次改密")
    return user


def require_admin(user: Annotated[dict[str, Any], Depends(current_user)]) -> dict[str, Any]:
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可操作")
    return user


def row_to_user_view(row: dict[str, Any] | Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "role": row["role"],
        "active": bool(row["active"]),
        "must_change_password": bool(row.get("must_change_password", row["must_change_password"])) if isinstance(row, dict) else bool(row["must_change_password"]),
    }


def get_owned_work(conn, user_id: str, work_id: str):
    work = conn.execute("SELECT * FROM works WHERE id=? AND user_id=?", (work_id, user_id)).fetchone()
    if not work:
        raise HTTPException(status_code=404, detail="作品不存在")
    return work


def ensure_run_capability(conn, user_id: str, work_id: str):
    work = get_owned_work(conn, user_id, work_id)
    active_for_user = conn.execute(
        "SELECT COUNT(*) AS total FROM works WHERE user_id=? AND status IN ('starting', 'running')", (user_id,)
    ).fetchone()["total"]
    if active_for_user >= settings.active_runs_per_operator:
        raise HTTPException(status_code=400, detail="已达到每位操作者的活跃创作运行上限")
    active_global = conn.execute(
        "SELECT COUNT(*) AS total FROM works WHERE status IN ('starting', 'running')"
    ).fetchone()["total"]
    if active_global >= settings.active_runs_global:
        raise HTTPException(status_code=400, detail="全站活跃创作运行已满")
    return work


def require_credential_if_needed(conn, user_id: str) -> None:
    if settings.engine_mode != "ainovel":
        return
    cred = conn.execute("SELECT last_test_status FROM credentials WHERE user_id=?", (user_id,)).fetchone()
    if not cred:
        raise HTTPException(status_code=400, detail="请先保存模型凭证")
    if cred["last_test_status"] != "success":
        raise HTTPException(status_code=400, detail="请先对已保存的模型凭证执行连接测试并确认成功")


def build_output_root(work_id: str):
    return engine_manager.output_root(work_id)


def build_download_headers(filename: str) -> dict[str, str]:
    ascii_fallback = ''.join(ch if ch.isascii() and (ch.isalnum() or ch in '._-') else '_' for ch in filename)
    ascii_fallback = ascii_fallback.strip('._') or 'download.txt'
    return {
        "Content-Disposition": f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(filename)}"
    }


def list_artifacts_for_work(work_id: str) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    work_dir = engine_manager.work_dir(work_id)
    output_root = build_output_root(work_id)
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
    return artifacts


def list_chapter_views(work_id: str) -> list[dict[str, Any]]:
    output_root = build_output_root(work_id)
    return [
        {
            "id": item.id,
            "index": item.index,
            "title": item.title,
            "filename": item.filename,
            "size": item.size,
            "updated_at": item.updated_at,
            "character_count": item.character_count,
            "paragraph_count": item.paragraph_count,
        }
        for item in list_chapters(output_root)
    ]


def credential_view(row) -> dict[str, Any]:
    return {
        "provider_alias": row["provider_alias"],
        "provider_type": row["provider_type"],
        "model_name": row["model_name"],
        "reasoning_effort": row["reasoning_effort"],
        "base_url": row["base_url"],
        "masked_api_key": row["masked_api_key"],
        "updated_at": row["updated_at"],
        "last_test_status": row["last_test_status"],
        "last_test_message": row["last_test_message"],
        "last_tested_at": row["last_tested_at"],
    }


def probe_model_connection(payload: CredentialPayload) -> tuple[bool, str, int | None, str | None]:
    if not payload.base_url:
        return False, "缺少 Base URL，无法测试连接", None, None
    provider_type = (payload.provider_type or "openai").lower()
    if provider_type in OPENAI_COMPATIBLE_TYPES:
        url = payload.base_url.rstrip("/") + "/chat/completions"
        body = {
            "model": payload.model_name,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 8,
            "temperature": 0,
        }
        headers = {"Authorization": f"Bearer {payload.api_key}", "Content-Type": "application/json"}
        with httpx.Client(timeout=25.0) as client:
            response = client.post(url, json=body, headers=headers)
        response.raise_for_status()
        data = response.json()
        preview = None
        try:
            preview = data["choices"][0]["message"]["content"]
        except Exception:
            preview = None
        return True, "连接成功", response.status_code, preview
    with httpx.Client(timeout=10.0, follow_redirects=True) as client:
        response = client.get(payload.base_url)
    response.raise_for_status()
    return True, "连接成功", response.status_code, None


@app.get("/api/health", response_model=HealthView)
def health() -> dict[str, Any]:
    return {"ok": True, "engine_mode": settings.engine_mode, "time": utcnow()}


@app.post("/api/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest) -> dict[str, Any]:
    with transaction() as conn:
        row = conn.execute("SELECT * FROM users WHERE username=? AND active=1", (payload.username,)).fetchone()
        if not row or not verify_password(payload.password, row["password_hash"]):
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        conn.execute("UPDATE users SET last_login_at=?, updated_at=? WHERE id=?", (utcnow(), utcnow(), row["id"]))
        row = conn.execute("SELECT * FROM users WHERE id=?", (row["id"],)).fetchone()
    token = issue_token({"sub": row["id"], "role": row["role"]})
    return {"token": token, "user": row_to_user_view(row)}


@app.post("/api/auth/claim", response_model=ActionResponse)
def claim(payload: InviteClaimRequest) -> ActionResponse:
    with transaction() as conn:
        invite = conn.execute("SELECT * FROM invites WHERE code=?", (payload.code,)).fetchone()
        if not invite:
            raise HTTPException(status_code=404, detail="邀请码不存在")
        if invite["revoked_at"]:
            raise HTTPException(status_code=400, detail="邀请码已作废")
        if is_expired(invite["expires_at"]):
            raise HTTPException(status_code=400, detail="邀请码已过期")
        if invite["used_count"] >= invite["max_uses"]:
            raise HTTPException(status_code=400, detail="邀请码已用完")
        exists = conn.execute("SELECT 1 FROM users WHERE username=?", (payload.username,)).fetchone()
        if exists:
            raise HTTPException(status_code=400, detail="用户名已存在")
        now = utcnow()
        conn.execute(
            """
            INSERT INTO users (
              id, username, display_name, password_hash, role, active,
              must_change_password, password_changed_at, last_login_at, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, 'operator', 1, 0, ?, NULL, ?, ?)
            """,
            (new_id("usr"), payload.username, payload.display_name, hash_password(payload.password), now, now, now),
        )
        conn.execute("UPDATE invites SET used_count=used_count+1 WHERE id=?", (invite["id"],))
    return ActionResponse(ok=True, message="领取账号成功")


@app.get("/api/me", response_model=MeView)
def me(user: Annotated[dict[str, Any], Depends(current_user)]) -> dict[str, Any]:
    return {"user": row_to_user_view(user)}


@app.post("/api/users/me/password", response_model=ActionResponse)
def change_password(payload: PasswordChangeRequest, user: Annotated[dict[str, Any], Depends(current_user)]) -> ActionResponse:
    if payload.current_password == payload.new_password:
        raise HTTPException(status_code=400, detail="新密码不能与旧密码相同")
    if not verify_password(payload.current_password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="当前密码不正确")
    now = utcnow()
    with transaction() as conn:
        conn.execute(
            "UPDATE users SET password_hash=?, must_change_password=0, password_changed_at=?, updated_at=? WHERE id=?",
            (hash_password(payload.new_password), now, now, user["id"]),
        )
    return ActionResponse(ok=True, message="密码修改成功")


@app.get("/api/system/overview", response_model=SystemOverviewView)
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
        "limits": {"per_operator": settings.active_runs_per_operator, "global": settings.active_runs_global},
        "engine_mode": settings.engine_mode,
    }


@app.get("/api/testing/connection-presets", response_model=list[ConnectionPresetView])
def get_connection_presets(admin: Annotated[dict[str, Any], Depends(require_admin)]) -> list[dict[str, str]]:
    return TEST_CONNECTION_PRESETS


@app.get("/api/invites", response_model=InviteListView)
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
                "created_at": row["created_at"],
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
            (new_id("inv"), secrets.token_urlsafe(8), payload.note, now_plus_hours(payload.expires_in_hours), payload.max_uses, admin["id"], utcnow()),
        )
    return ActionResponse(ok=True, message="邀请码已创建")


@app.post("/api/invites/{invite_id}/revoke", response_model=ActionResponse)
def revoke_invite(invite_id: str, admin: Annotated[dict[str, Any], Depends(require_admin)]) -> ActionResponse:
    with transaction() as conn:
        row = conn.execute("SELECT id, revoked_at FROM invites WHERE id=?", (invite_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="邀请码不存在")
        if not row["revoked_at"]:
            conn.execute("UPDATE invites SET revoked_at=? WHERE id=?", (utcnow(), invite_id))
    return ActionResponse(ok=True, message="邀请码已作废")


@app.get("/api/credentials/me", response_model=CredentialItemView)
def get_credential(user: Annotated[dict[str, Any], Depends(current_user)]) -> dict[str, Any]:
    with transaction() as conn:
        row = conn.execute("SELECT * FROM credentials WHERE user_id=?", (user["id"],)).fetchone()
        if not row:
            return {"item": None}
    return {"item": credential_view(row)}


@app.put("/api/credentials/me", response_model=ActionResponse)
def save_credential(payload: CredentialPayload, user: Annotated[dict[str, Any], Depends(current_user)]) -> ActionResponse:
    masked = f"{payload.api_key[:6]}***{payload.api_key[-4:]}" if len(payload.api_key) >= 10 else "***已保存***"
    now = utcnow()
    encrypted = encrypt_text(payload.api_key)
    with transaction() as conn:
        existing = conn.execute("SELECT id FROM credentials WHERE user_id=?", (user["id"],)).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE credentials SET provider_alias=?, provider_type=?, model_name=?, reasoning_effort=?, base_url=?,
                api_key_encrypted=?, masked_api_key=?, updated_at=?, last_test_status=NULL,
                last_test_message=NULL, last_tested_at=NULL WHERE user_id=?
                """,
                (payload.provider_alias, payload.provider_type, payload.model_name, payload.reasoning_effort, payload.base_url, encrypted, masked, now, user["id"]),
            )
        else:
            conn.execute(
                """
                INSERT INTO credentials (
                  id, user_id, provider_alias, provider_type, model_name, reasoning_effort, base_url,
                  api_key_encrypted, masked_api_key, updated_at, last_test_status, last_test_message, last_tested_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL)
                """,
                (new_id("cred"), user["id"], payload.provider_alias, payload.provider_type, payload.model_name, payload.reasoning_effort, payload.base_url, encrypted, masked, now),
            )
    return ActionResponse(ok=True, message="模型凭证已保存")


@app.post("/api/credentials/test", response_model=CredentialTestResponse)
def test_credential(payload: CredentialPayload, user: Annotated[dict[str, Any], Depends(current_user)]) -> dict[str, Any]:
    status = "failed"
    message = "连接失败"
    base_url_status: int | None = None
    preview: str | None = None
    try:
        ok, message, base_url_status, preview = probe_model_connection(payload)
        status = "success" if ok else "failed"
    except Exception as exc:
        message = f"连接失败：{exc}"
    with transaction() as conn:
        row = conn.execute("SELECT * FROM credentials WHERE user_id=?", (user["id"],)).fetchone()
        matches_saved = bool(
            row
            and row["provider_alias"] == payload.provider_alias
            and (row["provider_type"] or None) == (payload.provider_type or None)
            and row["model_name"] == payload.model_name
            and row["reasoning_effort"] == payload.reasoning_effort
            and (row["base_url"] or None) == (payload.base_url or None)
            and decrypt_text(row["api_key_encrypted"]) == payload.api_key
        )
        if matches_saved:
            now = utcnow()
            conn.execute(
                "UPDATE credentials SET last_test_status=?, last_test_message=?, last_tested_at=?, updated_at=? WHERE user_id=?",
                (status, message, now, now, user["id"]),
            )
        elif row:
            message = f"{message}；当前测试参数尚未保存，因此未更新已保存配置的连接状态"
    return {
        "ok": status == "success",
        "message": message,
        "engine_mode": settings.engine_mode,
        "base_url_status": base_url_status,
        "model_reply_preview": preview,
    }


@app.get("/api/works", response_model=WorkListView)
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
    work_dir = engine_manager.work_dir(work_id)
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
        "artifacts": list_artifacts_for_work(work_id),
        "chapters": list_chapter_views(work_id),
    }


@app.get("/api/works/{work_id}", response_model=WorkStatusView)
def get_work(work_id: str, user: Annotated[dict[str, Any], Depends(current_user)]) -> dict[str, Any]:
    return work_snapshot(work_id, user["id"])


@app.get("/api/works/{work_id}/chapters", response_model=ChapterListView)
def get_chapter_list(work_id: str, user: Annotated[dict[str, Any], Depends(current_user)]) -> dict[str, Any]:
    with transaction() as conn:
        get_owned_work(conn, user["id"], work_id)
    return {"items": list_chapter_views(work_id)}


@app.get("/api/works/{work_id}/chapters/{chapter_id}", response_model=ChapterDetailView)
def get_chapter_detail(work_id: str, chapter_id: str, user: Annotated[dict[str, Any], Depends(current_user)]) -> dict[str, Any]:
    with transaction() as conn:
        get_owned_work(conn, user["id"], work_id)
    item = load_chapter_by_id(build_output_root(work_id), chapter_id)
    if not item:
        raise HTTPException(status_code=404, detail="章节不存在")
    raw = item.path.read_text(encoding="utf-8", errors="ignore")
    return {
        "id": item.id,
        "index": item.index,
        "title": item.title,
        "filename": item.filename,
        "cleaned_text": render_chapter_txt(item),
        "raw_markdown": raw,
        "size": item.size,
        "updated_at": item.updated_at,
        "character_count": item.character_count,
        "paragraph_count": item.paragraph_count,
    }


@app.get("/api/works/{work_id}/chapters/{chapter_id}/download.txt")
def download_chapter_txt(work_id: str, chapter_id: str, user: Annotated[dict[str, Any], Depends(current_user)]):
    with transaction() as conn:
        get_owned_work(conn, user["id"], work_id)
    item = load_chapter_by_id(build_output_root(work_id), chapter_id)
    if not item:
        raise HTTPException(status_code=404, detail="章节不存在")
    txt = render_chapter_txt(item)
    filename = f"{item.title}.txt".replace("/", "-")
    headers = build_download_headers(filename)
    return PlainTextResponse(txt, headers=headers)


@app.get("/api/works/{work_id}/download/all.txt")
def download_all_txt(work_id: str, user: Annotated[dict[str, Any], Depends(current_user)]):
    with transaction() as conn:
        work = get_owned_work(conn, user["id"], work_id)
    output_root = build_output_root(work_id)
    if not list_chapters(output_root):
        raise HTTPException(status_code=404, detail="暂无可导出的章节")
    txt = render_all_chapters_txt(output_root, work["title"])
    headers = build_download_headers(f"{work["title"].replace("/", "-")}-all.txt")
    return PlainTextResponse(txt, headers=headers)


@app.post("/api/works/{work_id}/runs/start", response_model=ActionResponse)
def start_work(work_id: str, user: Annotated[dict[str, Any], Depends(current_user)]) -> ActionResponse:
    run_id = new_id("run")
    with transaction() as conn:
        work = ensure_run_capability(conn, user["id"], work_id)
        if work["status"] not in STARTABLE_STATUSES:
            raise HTTPException(status_code=400, detail="只有未开始的作品才能点击开始")
        require_credential_if_needed(conn, user["id"])
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
            conn.execute(
                "UPDATE runs SET status='failed', ended_at=?, updated_at=?, meta_json=? WHERE id=?",
                (utcnow(), utcnow(), json_dumps({"error": str(exc)}), run_id),
            )
            conn.execute(
                "UPDATE works SET status='failed', last_error=?, active_run_id=NULL, updated_at=? WHERE id=?",
                (str(exc), utcnow(), work_id),
            )
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    message = "真实小说引擎已启动" if settings.engine_mode == "ainovel" else "模拟验收运行已启动（不会调用大模型）"
    return ActionResponse(ok=True, message=message)


@app.post("/api/works/{work_id}/runs/pause", response_model=ActionResponse)
def pause_work(work_id: str, user: Annotated[dict[str, Any], Depends(current_user)]) -> ActionResponse:
    with transaction() as conn:
        work = get_owned_work(conn, user["id"], work_id)
        if work["status"] not in PAUSABLE_STATUSES or not work["active_run_id"]:
            raise HTTPException(status_code=400, detail="当前没有可暂停的活跃运行")
        run_id = work["active_run_id"]
    try:
        engine_manager.pause(run_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return ActionResponse(ok=True, message="暂停请求已发送")


@app.post("/api/works/{work_id}/runs/continue", response_model=ActionResponse)
def continue_work(work_id: str, user: Annotated[dict[str, Any], Depends(current_user)]) -> ActionResponse:
    run_id = new_id("run")
    with transaction() as conn:
        work = ensure_run_capability(conn, user["id"], work_id)
        if work["status"] not in CONTINUABLE_STATUSES:
            raise HTTPException(status_code=400, detail="只有暂停、额度熔断或失败后的作品才能继续创作")
        require_credential_if_needed(conn, user["id"])
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
            conn.execute(
                "UPDATE runs SET status='failed', ended_at=?, updated_at=?, meta_json=? WHERE id=?",
                (utcnow(), utcnow(), json_dumps({"error": str(exc)}), run_id),
            )
            conn.execute(
                "UPDATE works SET status='failed', last_error=?, active_run_id=NULL, updated_at=? WHERE id=?",
                (str(exc), utcnow(), work_id),
            )
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ActionResponse(ok=True, message="继续创作已启动")
