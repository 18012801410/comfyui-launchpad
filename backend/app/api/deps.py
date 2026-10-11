"""鉴权依赖：Bearer 令牌校验（除 /api/health 外全 API 强制）。"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.api.errors import auth_required, invalid_token
from app.core.config import PanelSettings, SettingsStore


def get_settings_store(request: Request) -> SettingsStore:
    store: SettingsStore = request.app.state.settings_store
    return store


def require_token(
    request: Request,
    store: Annotated[SettingsStore, Depends(get_settings_store)],
) -> PanelSettings:
    settings = store.load()
    if settings is None:
        raise auth_required("面板尚未初始化")
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise auth_required()
    token = header[len("Bearer ") :].strip()
    if not token or not store.verify(token):
        raise invalid_token()
    return settings


SettingsDep = Annotated[PanelSettings, Depends(require_token)]
