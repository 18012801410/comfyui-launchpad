"""认证路由：verify / rotate（API-002、API-003）。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app import __version__
from app.api.deps import get_settings_store, require_token
from app.api.envelope import ok
from app.api.errors import invalid_token
from app.core.config import PanelSettings, SettingsStore
from app.core.security import generate_token

router = APIRouter(prefix="/api/auth")

SettingsStoreDep = Annotated[SettingsStore, Depends(get_settings_store)]
SettingsDep = Annotated[PanelSettings, Depends(require_token)]


class VerifyBody(BaseModel):
    token: str


@router.post("/verify")
def verify(body: VerifyBody, store: SettingsStoreDep) -> dict[str, object]:
    if not store.verify(body.token):
        raise invalid_token()
    return ok({"panel_version": __version__})


@router.post("/rotate")
def rotate(request: Request, settings: SettingsDep) -> dict[str, object]:
    store: SettingsStore = request.app.state.settings_store
    new_token = generate_token()
    store.rotate_token(settings, new_token)
    # 新令牌明文仅此一次返回（API-003）
    return ok({"token": new_token})
