from __future__ import annotations

import os
from dataclasses import dataclass


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    if value is None and os.name == "nt":
        value = _windows_user_env(name)
    return (value if value is not None else default).strip()


def _windows_user_env(name: str) -> str | None:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
            return str(value)
    except OSError:
        return None


@dataclass(frozen=True)
class SyncConfig:
    media_upload_url: str
    media_bearer_token: str
    ssh_host: str
    ssh_port: int
    ssh_user: str
    ssh_key: str
    local_port: int
    mysql_remote_host: str
    mysql_remote_port: int
    mysql_host: str
    mysql_port: int
    mysql_db: str
    mysql_user: str
    mysql_password: str

    @classmethod
    def from_env(cls) -> "SyncConfig":
        return cls(
            media_upload_url=_env("SYNC_MEDIA_UPLOAD_URL"),
            media_bearer_token=_env("SYNC_MEDIA_BEARER_TOKEN"),
            ssh_host=_env("SYNC_SSH_HOST"),
            ssh_port=int(_env("SYNC_SSH_PORT", "22")),
            ssh_user=_env("SYNC_SSH_USER"),
            ssh_key=_env("SYNC_SSH_KEY"),
            local_port=int(_env("SYNC_LOCAL_PORT", "3307")),
            mysql_remote_host=_env("SYNC_MYSQL_REMOTE_HOST", "127.0.0.1"),
            mysql_remote_port=int(_env("SYNC_MYSQL_REMOTE_PORT", "3306")),
            mysql_host=_env("SYNC_MYSQL_HOST", "127.0.0.1"),
            mysql_port=int(_env("SYNC_MYSQL_PORT", _env("SYNC_LOCAL_PORT", "3307"))),
            mysql_db=_env("SYNC_MYSQL_DB"),
            mysql_user=_env("SYNC_MYSQL_USER"),
            mysql_password=_env("SYNC_MYSQL_PASSWORD"),
        )

    def missing_for_media(self) -> list[str]:
        required = {
            "SYNC_MEDIA_UPLOAD_URL": self.media_upload_url,
            "SYNC_MEDIA_BEARER_TOKEN": self.media_bearer_token,
        }
        return [name for name, value in required.items() if not value]

    def missing_for_mysql(self) -> list[str]:
        required = {
            "SYNC_SSH_HOST": self.ssh_host,
            "SYNC_SSH_USER": self.ssh_user,
            "SYNC_SSH_KEY": self.ssh_key,
            "SYNC_MYSQL_DB": self.mysql_db,
            "SYNC_MYSQL_USER": self.mysql_user,
            "SYNC_MYSQL_PASSWORD": self.mysql_password,
        }
        return [name for name, value in required.items() if not value]


def is_enabled() -> bool:
    return _env("SYNC_ENABLED") == "1"
