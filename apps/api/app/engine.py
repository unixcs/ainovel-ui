from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import docker
from docker.errors import DockerException, NotFound

from .config import settings
from .db import json_dumps, transaction, utcnow
from .security import decrypt_text


class EngineManager:
    def __init__(self) -> None:
        self._threads: dict[str, tuple[threading.Thread, threading.Event]] = {}
        self._docker = None
        if settings.engine_mode == "ainovel":
            try:
                self._docker = docker.from_env()
            except DockerException:
                self._docker = None

    def work_dir(self, work_id: str) -> Path:
        path = settings.works_dir / work_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def output_root(self, work_id: str) -> Path:
        work_dir = self.work_dir(work_id)
        if settings.engine_mode == "ainovel":
            return work_dir / "workspace" / "output" / "novel"
        return work_dir / "output" / "novel"

    def start(self, work_id: str, run_id: str, prompt: str, resume: bool = False) -> None:
        if settings.engine_mode == "ainovel":
            self._start_ainovel(work_id, run_id, prompt, resume=resume)
        else:
            self._start_mock(work_id, run_id, prompt, resume=resume)

    def pause(self, run_id: str) -> None:
        if settings.engine_mode == "ainovel":
            self._pause_ainovel(run_id)
        else:
            thread_info = self._threads.get(run_id)
            if thread_info:
                _, stop_event = thread_info
                stop_event.set()

    def sync_work(self, work_id: str) -> None:
        if settings.engine_mode != "ainovel" or not self._docker:
            return
        with transaction() as conn:
            run = conn.execute(
                "SELECT * FROM runs WHERE work_id=? AND status IN ('starting', 'running') ORDER BY created_at DESC LIMIT 1",
                (work_id,),
            ).fetchone()
            if not run or not run["container_name"]:
                return
            try:
                container = self._docker.containers.get(run["container_name"])
                container.reload()
            except NotFound:
                self._mark_failed(conn, run["id"], work_id, "运行容器丢失")
                return
            state = container.attrs.get("State", {})
            status = state.get("Status")
            if status == "running":
                conn.execute(
                    "UPDATE runs SET status='running', updated_at=? WHERE id=?",
                    (utcnow(), run["id"]),
                )
                conn.execute(
                    "UPDATE works SET status='running', current_phase='写作', current_flow='writing', updated_at=? WHERE id=?",
                    (utcnow(), work_id),
                )
                return
            exit_code = state.get("ExitCode", 1)
            if exit_code == 0:
                conn.execute(
                    "UPDATE runs SET status='completed', ended_at=?, updated_at=? WHERE id=?",
                    (utcnow(), utcnow(), run["id"]),
                )
                progress_path = self.output_root(work_id) / "progress.json"
                completed = 0
                if progress_path.exists():
                    try:
                        completed = int(json.loads(progress_path.read_text(encoding="utf-8")).get("current_chapter", 0))
                    except Exception:
                        completed = 0
                conn.execute(
                    "UPDATE works SET status='completed', current_phase='完成', current_flow='done', completed_chapters=?, active_run_id=NULL, updated_at=? WHERE id=?",
                    (completed, utcnow(), work_id),
                )
            else:
                logs = ""
                try:
                    logs = container.logs(tail=60).decode("utf-8", errors="ignore")[-1000:]
                except Exception:
                    logs = "容器退出，日志读取失败"
                self._mark_failed(conn, run["id"], work_id, logs)

    def _mark_failed(self, conn, run_id: str, work_id: str, error_text: str) -> None:
        conn.execute(
            "UPDATE runs SET status='failed', ended_at=?, updated_at=?, meta_json=? WHERE id=?",
            (utcnow(), utcnow(), json_dumps({"error": error_text}), run_id),
        )
        conn.execute(
            "UPDATE works SET status='failed', last_error=?, active_run_id=NULL, updated_at=? WHERE id=?",
            (error_text, utcnow(), work_id),
        )

    def _start_mock(self, work_id: str, run_id: str, prompt: str, resume: bool = False) -> None:
        stop_event = threading.Event()
        thread = threading.Thread(target=self._mock_worker, args=(work_id, run_id, prompt, stop_event, resume), daemon=True)
        self._threads[run_id] = (thread, stop_event)
        thread.start()

    def _mock_worker(self, work_id: str, run_id: str, prompt: str, stop_event: threading.Event, resume: bool) -> None:
        output_dir = self.output_root(work_id)
        chapters_dir = output_dir / "chapters"
        output_dir.mkdir(parents=True, exist_ok=True)
        chapters_dir.mkdir(parents=True, exist_ok=True)
        with transaction() as conn:
            row = conn.execute("SELECT completed_chapters FROM works WHERE id=?", (work_id,)).fetchone()
            completed = int(row["completed_chapters"] if row else 0)
            conn.execute(
                "UPDATE runs SET status='running', updated_at=?, started_at=COALESCE(started_at, ?) WHERE id=?",
                (utcnow(), utcnow(), run_id),
            )
            conn.execute(
                "UPDATE works SET status='running', current_phase='初始化', current_flow='booting', updated_at=? WHERE id=?",
                (utcnow(), work_id),
            )
        phases = [("初始化", "booting"), ("设定", "planning"), ("大纲", "outlining"), ("写作", "writing")]
        for phase, flow in phases:
            if stop_event.is_set():
                self._pause_mock(work_id, run_id)
                return
            with transaction() as conn:
                conn.execute(
                    "UPDATE works SET current_phase=?, current_flow=?, updated_at=? WHERE id=?",
                    (phase, flow, utcnow(), work_id),
                )
            time.sleep(1)
        outline_path = output_dir / "outline.md"
        if not outline_path.exists():
            outline_path.write_text(f"# 大纲\n\n- 核心创作指令：{prompt}\n- 本文件由 mock 引擎生成，用于 WSL / 云上验收。\n", encoding="utf-8")
        for idx in range(completed + 1, completed + 4):
            if stop_event.is_set():
                self._pause_mock(work_id, run_id)
                return
            chapter_path = chapters_dir / f"{idx:03d}-第{idx}章.md"
            chapter_path.write_text(
                f"# 第{idx}章\n\n这是小白一号 mock 引擎生成的验收章节。\n\n原始快速开始：{prompt}\n",
                encoding="utf-8",
            )
            progress = {
                "current_chapter": idx,
                "target_chapters": idx + 6,
                "current_phase": "writing",
                "updated_at": utcnow(),
            }
            (output_dir / "progress.json").write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")
            with transaction() as conn:
                conn.execute(
                    "UPDATE works SET status='running', current_phase='写作', current_flow='writing', completed_chapters=?, updated_at=? WHERE id=?",
                    (idx, utcnow(), work_id),
                )
            time.sleep(1)
        with transaction() as conn:
            conn.execute(
                "UPDATE runs SET status='completed', ended_at=?, updated_at=? WHERE id=?",
                (utcnow(), utcnow(), run_id),
            )
            conn.execute(
                "UPDATE works SET status='completed', current_phase='完成', current_flow='done', active_run_id=NULL, updated_at=? WHERE id=?",
                (utcnow(), work_id),
            )

    def _pause_mock(self, work_id: str, run_id: str) -> None:
        with transaction() as conn:
            conn.execute("UPDATE runs SET status='paused', ended_at=?, updated_at=? WHERE id=?", (utcnow(), utcnow(), run_id))
            conn.execute(
                "UPDATE works SET status='paused', current_phase='已暂停', current_flow='paused', active_run_id=NULL, updated_at=? WHERE id=?",
                (utcnow(), work_id),
            )

    def _start_ainovel(self, work_id: str, run_id: str, prompt: str, resume: bool = False) -> None:
        if not self._docker:
            raise RuntimeError("Docker daemon 不可用，无法启动 ainovel-cli")
        work_dir = self.work_dir(work_id)
        config_dir = work_dir / "config"
        workspace_dir = work_dir / "workspace"
        config_dir.mkdir(parents=True, exist_ok=True)
        workspace_dir.mkdir(parents=True, exist_ok=True)
        self._write_ainovel_config(work_id, config_dir / "config.json")
        container_name = f"xiaobai-{run_id}"
        command = [] if resume else ["--headless", "--prompt", prompt]
        kwargs: dict[str, Any] = {
            "image": settings.ainovel_image,
            "name": container_name,
            "detach": True,
            "working_dir": "/workspace",
            "volumes": {
                str(config_dir.resolve()): {"bind": "/root/.ainovel", "mode": "rw"},
                str(workspace_dir.resolve()): {"bind": "/workspace", "mode": "rw"},
            },
            "labels": {
                "com.xiaobai.app": "xiaobai-one",
                "com.xiaobai.work_id": work_id,
                "com.xiaobai.run_id": run_id,
            },
        }
        if settings.ainovel_network:
            kwargs["network"] = settings.ainovel_network
        self._docker.containers.run(command=command, **kwargs)
        with transaction() as conn:
            conn.execute(
                "UPDATE runs SET status='starting', container_name=?, meta_json=?, started_at=COALESCE(started_at, ?), updated_at=? WHERE id=?",
                (container_name, json_dumps({"resume": resume}), utcnow(), utcnow(), run_id),
            )
            conn.execute(
                "UPDATE works SET status='starting', current_phase='启动中', current_flow='booting', updated_at=? WHERE id=?",
                (utcnow(), work_id),
            )

    def _pause_ainovel(self, run_id: str) -> None:
        if not self._docker:
            return
        with transaction() as conn:
            run = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if not run or not run["container_name"]:
                return
            try:
                container = self._docker.containers.get(run["container_name"])
                container.stop(timeout=10)
            except NotFound:
                pass
            conn.execute("UPDATE runs SET status='paused', ended_at=?, updated_at=? WHERE id=?", (utcnow(), utcnow(), run_id))
            conn.execute(
                "UPDATE works SET status='paused', current_phase='已暂停', current_flow='paused', active_run_id=NULL, updated_at=? WHERE id=?",
                (utcnow(), run["work_id"]),
            )

    def _write_ainovel_config(self, work_id: str, target: Path) -> None:
        with transaction() as conn:
            work = conn.execute("SELECT * FROM works WHERE id=?", (work_id,)).fetchone()
            cred = conn.execute("SELECT * FROM credentials WHERE user_id=?", (work["user_id"],)).fetchone() if work else None
        if not work or not cred:
            raise RuntimeError("缺少模型凭证，无法生成 ainovel 配置")
        alias = cred["provider_alias"]
        provider_type = cred["provider_type"]
        payload = {
            "provider": alias,
            "model": cred["model_name"],
            "reasoning_effort": cred["reasoning_effort"],
            "style": work["style"],
            "providers": {
                alias: {
                    "api_key": decrypt_text(cred["api_key_encrypted"]),
                    "models": [{"name": cred["model_name"]}],
                }
            },
        }
        if provider_type:
            payload["providers"][alias]["type"] = provider_type
        if cred["base_url"]:
            payload["providers"][alias]["base_url"] = cred["base_url"]
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


engine_manager = EngineManager()
