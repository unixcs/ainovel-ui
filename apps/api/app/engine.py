from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import docker
from docker.errors import DockerException, NotFound

from .config import settings
from .content import list_chapters
from .db import json_dumps, transaction, utcnow
from .security import decrypt_text


class EngineManager:
    def __init__(self) -> None:
        self._threads: dict[str, tuple[threading.Thread, threading.Event]] = {}
        self._monitors: dict[str, threading.Thread] = {}
        self._control_lock = threading.RLock()
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

    def host_work_dir(self, work_id: str) -> Path:
        if settings.host_data_dir is None:
            raise RuntimeError("未配置宿主机数据目录")
        path = settings.host_data_dir / "works" / work_id
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
        if settings.engine_mode != "ainovel":
            return
        with self._control_lock:
            with transaction() as conn:
                row = conn.execute(
                    "SELECT * FROM runs WHERE work_id=? AND status IN ('starting', 'running') ORDER BY created_at DESC LIMIT 1",
                    (work_id,),
                ).fetchone()
                run = dict(row) if row else None
                work = conn.execute("SELECT target_chapters FROM works WHERE id=?", (work_id,)).fetchone()
                target = int(work["target_chapters"] or 0) if work else 0
            if not run:
                return
            if not run.get("container_name"):
                return
            if not self._docker:
                self._fail_active_run(run["id"], work_id, "Docker daemon 不可用，无法继续监控真实小说引擎")
                return

            completed = len(list_chapters(self.output_root(work_id)))
            try:
                container = self._docker.containers.get(run["container_name"])
                container.reload()
            except NotFound:
                self._fail_active_run(run["id"], work_id, "运行容器丢失")
                return
            except DockerException as exc:
                self._fail_active_run(run["id"], work_id, f"Docker 状态读取失败：{exc}")
                return

            state = container.attrs.get("State", {})
            status = state.get("Status")
            if status in {"created", "restarting"}:
                now = utcnow()
                with transaction() as conn:
                    conn.execute(
                        "UPDATE runs SET status='starting', updated_at=? WHERE id=? AND status IN ('starting', 'running')",
                        (now, run["id"]),
                    )
                    conn.execute(
                        "UPDATE works SET status='starting', current_phase='启动中', current_flow='booting', completed_chapters=?, updated_at=? WHERE id=? AND active_run_id=?",
                        (completed, now, work_id, run["id"]),
                    )
                return

            if status == "running":
                if target and completed >= target:
                    stop_error = None
                    try:
                        container.stop(timeout=20)
                    except DockerException as exc:
                        stop_error = str(exc)
                        try:
                            container.kill()
                            stop_error = None
                        except DockerException as kill_exc:
                            stop_error = f"stop: {exc}; kill: {kill_exc}"
                    if stop_error:
                        now = utcnow()
                        message = f"已达到目标章节，但停止引擎失败，将自动重试：{stop_error}"
                        with transaction() as conn:
                            conn.execute(
                                "UPDATE runs SET meta_json=?, updated_at=? WHERE id=? AND status IN ('starting', 'running')",
                                (json_dumps({"target_stop_error": stop_error, "target": target}), now, run["id"]),
                            )
                            conn.execute(
                                "UPDATE works SET status='running', current_phase='达到目标，正在停止', current_flow='stopping', completed_chapters=?, last_error=?, updated_at=? WHERE id=? AND active_run_id=?",
                                (completed, message, now, work_id, run["id"]),
                            )
                        return
                    now = utcnow()
                    with transaction() as conn:
                        conn.execute(
                            "UPDATE runs SET status='completed', ended_at=?, updated_at=?, meta_json=? WHERE id=? AND status IN ('starting', 'running')",
                            (now, now, json_dumps({"stopped_at_target": target}), run["id"]),
                        )
                        conn.execute(
                            "UPDATE works SET status='completed', current_phase='完成', current_flow='done', completed_chapters=?, active_run_id=NULL, last_error=NULL, updated_at=? WHERE id=? AND active_run_id=?",
                            (completed, now, work_id, run["id"]),
                        )
                    self._remove_container(container)
                    return
                now = utcnow()
                phase = "写作" if completed else "构思与初始化"
                flow = "writing" if completed else "planning"
                with transaction() as conn:
                    conn.execute(
                        "UPDATE runs SET status='running', updated_at=? WHERE id=? AND status IN ('starting', 'running')",
                        (now, run["id"]),
                    )
                    conn.execute(
                        "UPDATE works SET status='running', current_phase=?, current_flow=?, completed_chapters=?, last_error=NULL, updated_at=? WHERE id=? AND active_run_id=?",
                        (phase, flow, completed, now, work_id, run["id"]),
                    )
                return

            exit_code = state.get("ExitCode", 1)
            if exit_code == 0 and completed > 0:
                now = utcnow()
                with transaction() as conn:
                    conn.execute(
                        "UPDATE runs SET status='completed', ended_at=?, updated_at=? WHERE id=? AND status IN ('starting', 'running')",
                        (now, now, run["id"]),
                    )
                    conn.execute(
                        "UPDATE works SET status='completed', current_phase='完成', current_flow='done', completed_chapters=?, active_run_id=NULL, last_error=NULL, updated_at=? WHERE id=? AND active_run_id=?",
                        (completed, now, work_id, run["id"]),
                    )
                self._remove_container(container)
                return

            try:
                logs = container.logs(tail=80).decode("utf-8", errors="ignore")[-2000:]
            except Exception:
                logs = "容器退出，日志读取失败"
            if exit_code == 0 and not completed:
                logs = f"引擎已正常退出，但没有生成任何章节。\n{logs}".strip()
            self._fail_active_run(run["id"], work_id, logs)
            self._remove_container(container)

    def recover_active_runs(self) -> None:
        if settings.engine_mode != "ainovel":
            return
        with transaction() as conn:
            rows = conn.execute(
                "SELECT id, work_id, container_name FROM runs WHERE status IN ('starting', 'running')"
            ).fetchall()
        for row in rows:
            if not row["container_name"]:
                self._fail_active_run(row["id"], row["work_id"], "API 重启时发现任务尚未成功创建运行容器")
        rows = [row for row in rows if row["container_name"]]
        if not self._docker:
            for row in rows:
                self._fail_active_run(row["id"], row["work_id"], "API 重启后无法连接 Docker daemon，真实引擎监控已安全停止")
            return
        for row in rows:
            if row["id"] in self._monitors:
                continue
            monitor = threading.Thread(target=self._monitor_ainovel, args=(row["work_id"], row["id"]), daemon=True)
            self._monitors[row["id"]] = monitor
            monitor.start()

    def _fail_active_run(self, run_id: str, work_id: str, error_text: str) -> None:
        now = utcnow()
        with transaction() as conn:
            cursor = conn.execute(
                "UPDATE runs SET status='failed', ended_at=?, updated_at=?, meta_json=? WHERE id=? AND status IN ('starting', 'running')",
                (now, now, json_dumps({"error": error_text}), run_id),
            )
            if cursor.rowcount:
                conn.execute(
                    "UPDATE works SET status='failed', last_error=?, active_run_id=NULL, updated_at=? WHERE id=? AND active_run_id=?",
                    (error_text, now, work_id, run_id),
                )

    def _start_mock(self, work_id: str, run_id: str, prompt: str, resume: bool = False) -> None:
        stop_event = threading.Event()
        thread = threading.Thread(target=self._mock_worker_entry, args=(work_id, run_id, prompt, stop_event, resume), daemon=True)
        self._threads[run_id] = (thread, stop_event)
        thread.start()

    def _mock_worker_entry(self, work_id: str, run_id: str, prompt: str, stop_event: threading.Event, resume: bool) -> None:
        try:
            self._mock_worker(work_id, run_id, prompt, stop_event, resume)
        finally:
            self._threads.pop(run_id, None)

    def _mock_worker(self, work_id: str, run_id: str, prompt: str, stop_event: threading.Event, resume: bool) -> None:
        output_dir = self.output_root(work_id)
        chapters_dir = output_dir / "chapters"
        output_dir.mkdir(parents=True, exist_ok=True)
        chapters_dir.mkdir(parents=True, exist_ok=True)
        with transaction() as conn:
            row = conn.execute("SELECT completed_chapters, target_chapters FROM works WHERE id=?", (work_id,)).fetchone()
            completed = int(row["completed_chapters"] if row else 0)
            target = int(row["target_chapters"] or 0) if row else 0
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
        remaining = max(target - completed, 0) if target else 3
        chapter_total = min(3, remaining)
        for idx in range(completed + 1, completed + chapter_total + 1):
            if stop_event.is_set():
                self._pause_mock(work_id, run_id)
                return
            chapter_path = chapters_dir / f"{idx:03d}-第{idx}章.md"
            chapter_path.write_text(
                f"# 第{idx}章 模拟章节\n\n"
                "> 注意：这是用于检查界面和工作流的模拟内容，不是大模型生成的正式小说。\n\n"
                f"创作任务是：{prompt}\n\n"
                "山风掠过城墙，灯火沿长街次第亮起。主角停在门前，第一次意识到，"
                "那个看似普通的决定已经改变了所有人的命运。\n\n"
                "他没有立刻向前。远处传来的脚步声越来越近，旧日线索与眼前危机交织，"
                "迫使他在退让与承担之间作出选择。\n\n"
                "当门扉终于打开时，新的矛盾也随之出现。本段仅用于验证章节列表、实时刷新、"
                "全文复制和 txt 导出是否完整工作。\n",
                encoding="utf-8",
            )
            progress = {
                "current_chapter": idx,
                "target_chapters": target or idx,
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
                "UPDATE works SET status='completed', current_phase='完成', current_flow='done', completed_chapters=?, active_run_id=NULL, updated_at=? WHERE id=?",
                (completed + chapter_total, utcnow(), work_id),
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
        host_work_dir = self.host_work_dir(work_id)
        config_dir = work_dir / "config"
        workspace_dir = work_dir / "workspace"
        host_config_dir = host_work_dir / "config"
        host_workspace_dir = host_work_dir / "workspace"
        config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        workspace_dir.mkdir(parents=True, exist_ok=True)
        host_config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        host_workspace_dir.mkdir(parents=True, exist_ok=True)
        config_dir.chmod(0o700)
        self._write_ainovel_config(work_id, config_dir / "config.json")
        container_name = f"xiaobai-{run_id}"
        command = ["--headless"] if resume else ["--headless", "--prompt", prompt]
        kwargs: dict[str, Any] = {
            "image": settings.ainovel_image,
            "name": container_name,
            "detach": True,
            "working_dir": "/workspace",
            "volumes": {
                str(host_config_dir.resolve()): {"bind": "/root/.ainovel", "mode": "rw"},
                str(host_workspace_dir.resolve()): {"bind": "/workspace", "mode": "rw"},
            },
            "mem_limit": settings.ainovel_memory,
            "nano_cpus": int(settings.ainovel_cpus * 1_000_000_000),
            "pids_limit": settings.ainovel_pids_limit,
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
        monitor = threading.Thread(target=self._monitor_ainovel, args=(work_id, run_id), daemon=True)
        self._monitors[run_id] = monitor
        monitor.start()

    def _monitor_ainovel(self, work_id: str, run_id: str) -> None:
        try:
            while True:
                self.sync_work(work_id)
                with transaction() as conn:
                    row = conn.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()
                if not row or row["status"] not in {"starting", "running"}:
                    return
                time.sleep(1)
        finally:
            self._monitors.pop(run_id, None)

    @staticmethod
    def _remove_container(container: Any) -> None:
        try:
            container.remove()
        except (DockerException, AttributeError):
            # Runtime state is already persisted; cleanup failure must not turn a
            # successful or failed run back into an active one.
            return

    def _pause_ainovel(self, run_id: str) -> None:
        if not self._docker:
            raise RuntimeError("Docker daemon 不可用，无法暂停 ainovel-cli")
        with self._control_lock:
            with transaction() as conn:
                row = conn.execute(
                    "SELECT * FROM runs WHERE id=? AND status IN ('starting', 'running')",
                    (run_id,),
                ).fetchone()
                run = dict(row) if row else None
            if not run or not run.get("container_name"):
                return
            try:
                container = self._docker.containers.get(run["container_name"])
                container.stop(timeout=10)
            except NotFound:
                self._fail_active_run(run_id, run["work_id"], "暂停时发现运行容器已丢失")
                return
            except DockerException as exc:
                raise RuntimeError(f"暂停引擎失败：{exc}") from exc
            now = utcnow()
            with transaction() as conn:
                cursor = conn.execute(
                    "UPDATE runs SET status='paused', ended_at=?, updated_at=? WHERE id=? AND status IN ('starting', 'running')",
                    (now, now, run_id),
                )
                if cursor.rowcount:
                    conn.execute(
                        "UPDATE works SET status='paused', current_phase='已暂停', current_flow='paused', active_run_id=NULL, last_error=NULL, updated_at=? WHERE id=? AND active_run_id=?",
                        (now, run["work_id"], run_id),
                    )
            self._remove_container(container)

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
        target.chmod(0o600)


engine_manager = EngineManager()
