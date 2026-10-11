"""面板设置与状态 JSON 持久化：原子写 + .bak 备份 + 损坏回退。

不变量（docs/ARCHITECTURE.md #2 原子写）：先写临时文件再 os.replace；
replace 失败时清理临时文件，正式路径保持旧内容；读取时主文件损坏自动回退 .bak。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.core.security import hash_token, new_salt, verify_token


class ConfigCorruptedError(RuntimeError):
    """主文件与备份均损坏。"""


class Channels(BaseModel):
    """分发渠道（提供方边界，可配置替换）。"""

    versions: str = "https://github.com/REPLACE_ME/launchpad-versions/releases"
    workflows: str = "https://github.com/REPLACE_ME/launchpad-workflows/releases"
    self_channel: str = "https://github.com/REPLACE_ME/launchpad-panel/releases"

    model_config = {"populate_by_name": True}


class PanelSettings(BaseModel):
    token_hash: str
    salt: str
    panel_port: int = 6006
    channels: Channels = Field(default_factory=Channels)
    academic_accel_default: bool = True
    theme: Literal["system", "light", "dark"] = "system"
    autostart_enabled: bool = True
    first_installed_at: datetime | None = None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def write_json_atomic(path: Path, data: dict[str, object]) -> None:
    """原子写 JSON：临时文件 → 备份旧文件 → os.replace。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if path.exists():
            bak = path.with_name(path.name + ".bak")
            bak.write_bytes(path.read_bytes())
        os.replace(tmp, path)
    except BaseException:
        if tmp.exists():
            tmp.unlink()
        raise


def read_json_with_backup(path: Path) -> dict[str, object]:
    """读取 JSON；主文件损坏回退 .bak；二者皆损坏抛 ConfigCorruptedError。"""
    for candidate in (path, path.with_name(path.name + ".bak")):
        if not candidate.exists():
            continue
        try:
            return dict(json.loads(candidate.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            continue
    if path.exists() or path.with_name(path.name + ".bak").exists():
        raise ConfigCorruptedError(f"配置损坏且无有效备份: {path}")
    return {}


class SettingsStore:
    """config.json 的类型化读写。首次初始化用 initialize()。"""

    def __init__(self, path: Path) -> None:
        self.path = path

    def exists(self) -> bool:
        return self.path.exists()

    def initialize(self, token: str) -> PanelSettings:
        settings = _with_token(
            PanelSettings(token_hash="", salt="", first_installed_at=utcnow()), token
        )
        self.save(settings)
        return settings

    def load(self) -> PanelSettings | None:
        if not self.path.exists():
            return None
        raw = read_json_with_backup(self.path)
        if not raw:
            return None
        return PanelSettings.model_validate(raw)

    def save(self, settings: PanelSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(self.path, settings.model_dump(mode="json"))

    def verify(self, token: str) -> bool:
        settings = self.load()
        if settings is None:
            return False
        return verify_token(token, settings.salt, settings.token_hash)

    def rotate_token(self, old_settings: PanelSettings, new_token: str) -> PanelSettings:
        settings = _with_token(old_settings, new_token)
        self.save(settings)
        return settings


def _with_token(settings: PanelSettings, token: str) -> PanelSettings:
    salt = new_salt()
    return settings.model_copy(update={"salt": salt, "token_hash": hash_token(token, salt)})
