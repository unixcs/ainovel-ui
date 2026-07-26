from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class Settings:
    app_name: str = "小白一号 API"
    data_dir: Path = Path(os.getenv("XIAOBAI_DATA_DIR", "/data"))
    db_path: Path = Path(os.getenv("XIAOBAI_DB_PATH", "/data/xiaobai.db"))
    host_data_dir: Path | None = None
    secret_key: str = os.getenv("XIAOBAI_SECRET_KEY", "dev-secret-change-me")
    bootstrap_admin_username: str = os.getenv("XIAOBAI_BOOTSTRAP_ADMIN_USERNAME", "admin")
    bootstrap_admin_password: str = os.getenv("XIAOBAI_BOOTSTRAP_ADMIN_PASSWORD", "ChangeMe123!")
    bootstrap_admin_display_name: str = os.getenv("XIAOBAI_BOOTSTRAP_ADMIN_DISPLAY_NAME", "引导管理员")
    api_host: str = os.getenv("XIAOBAI_API_HOST", "0.0.0.0")
    api_port: int = int(os.getenv("XIAOBAI_API_PORT", "8000"))
    cors_origin: str = os.getenv("XIAOBAI_CORS_ORIGIN", "*")
    engine_mode: str = os.getenv("XIAOBAI_ENGINE_MODE", "mock")
    ainovel_image: str = os.getenv("XIAOBAI_AINOVEL_IMAGE", "ghcr.io/voocel/ainovel-cli:latest")
    ainovel_network: str | None = os.getenv("XIAOBAI_AINOVEL_NETWORK")
    ainovel_memory: str = os.getenv("XIAOBAI_AINOVEL_MEMORY", "768m")
    ainovel_cpus: float = float(os.getenv("XIAOBAI_AINOVEL_CPUS", "1.0"))
    ainovel_pids_limit: int = int(os.getenv("XIAOBAI_AINOVEL_PIDS_LIMIT", "256"))
    active_runs_per_operator: int = int(os.getenv("XIAOBAI_ACTIVE_RUNS_PER_OPERATOR", "1"))
    active_runs_global: int = int(os.getenv("XIAOBAI_ACTIVE_RUNS_GLOBAL", "2"))

    def __post_init__(self) -> None:
        host_data_dir = os.getenv("XIAOBAI_HOST_DATA_DIR", "").strip()
        if self.host_data_dir is None:
            if host_data_dir:
                self.host_data_dir = Path(host_data_dir)
            elif self.engine_mode == "ainovel":
                raise ValueError("ainovel 模式必须设置 XIAOBAI_HOST_DATA_DIR 为宿主机数据目录的绝对路径")
            else:
                self.host_data_dir = self.data_dir
        if self.engine_mode == "ainovel" and not self.host_data_dir.is_absolute():
            raise ValueError("ainovel 模式的 XIAOBAI_HOST_DATA_DIR 必须是绝对路径")
        if self.engine_mode not in {"mock", "ainovel"}:
            raise ValueError("XIAOBAI_ENGINE_MODE 只能是 mock 或 ainovel")
        if self.ainovel_cpus <= 0 or self.ainovel_pids_limit <= 0:
            raise ValueError("ainovel 资源限制必须大于 0")

    @property
    def works_dir(self) -> Path:
        return self.data_dir / "works"

    @property
    def auth_secret(self) -> bytes:
        return self.secret_key.encode("utf-8")

    @property
    def fernet_key(self) -> bytes:
        raw = self.secret_key.encode("utf-8")
        padded = (raw * (32 // len(raw) + 1))[:32]
        return base64.urlsafe_b64encode(padded)


settings = Settings()
