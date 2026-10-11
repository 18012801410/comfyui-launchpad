"""插件管理路由（API-011/012）。"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from app.api.deps import require_token
from app.api.envelope import ok
from app.api.errors import AppError
from app.core.config import PanelSettings
from app.domain.plugin_manager import (
    check_update,
    scan_plugins,
    set_plugin_enabled,
    update_plugin,
)
from app.domain.version_manager import resolve_current_dir

router = APIRouter(prefix="/api/plugins")

SettingsDep = Annotated[PanelSettings, Depends(require_token)]


def _custom_nodes(request: Request) -> Path:
    version_dir = resolve_current_dir(request.app.state.layout)
    if version_dir is None:
        raise AppError(
            "version_not_installed", "尚未安装任何 ComfyUI 版本", status=404
        )
    return version_dir / "custom_nodes"


@router.get("")
def list_plugins(
    request: Request,
    _s: SettingsDep,
    check_updates: bool = Query(default=False),
) -> dict[str, object]:
    base = _custom_nodes(request)
    items = [p.to_dict() for p in scan_plugins(base)]
    if check_updates:
        for item in items:
            item["update_status"] = check_update(base, item["dir_name"])
    return ok({"items": items})


@router.post("/{dir_name}/update")
def update(dir_name: str, request: Request, _s: SettingsDep) -> dict[str, object]:
    message = update_plugin(_custom_nodes(request), dir_name)
    return ok({"message": message})


class EnableBody(BaseModel):
    enabled: bool


@router.post("/{dir_name}/enable")
def enable(
    dir_name: str, body: EnableBody, request: Request, _s: SettingsDep
) -> dict[str, object]:
    message = set_plugin_enabled(_custom_nodes(request), dir_name, body.enabled)
    return ok({"message": message})
