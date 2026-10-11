"""面板设置路由（API-017）：读不含令牌，写走白名单字段。"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.api.deps import require_token
from app.api.envelope import ok
from app.api.errors import invalid_launch_args
from app.core.config import Channels, PanelSettings, SettingsStore

router = APIRouter(prefix="/api/panel")

SettingsDep = Annotated[PanelSettings, Depends(require_token)]


class SettingsUpdate(BaseModel):
    panel_port: int | None = Field(default=None, ge=1024, le=65535)
    academic_accel_default: bool | None = None
    theme: Literal["system", "light", "dark"] | None = None
    autostart_enabled: bool | None = None
    channels: Channels | None = None


def _public(settings: PanelSettings) -> dict[str, object]:
    """不含任何令牌材料的公开视图。"""
    return {
        "panel_port": settings.panel_port,
        "academic_accel_default": settings.academic_accel_default,
        "theme": settings.theme,
        "autostart_enabled": settings.autostart_enabled,
        "channels": settings.channels.model_dump(by_alias=True),
    }


@router.get("/settings")
def get_settings(settings: SettingsDep) -> dict[str, object]:
    return ok(_public(settings))


@router.put("/settings")
def put_settings(
    body: SettingsUpdate,
    request: Request,
    settings: SettingsDep,
) -> dict[str, object]:
    store: SettingsStore = request.app.state.settings_store
    update = body.model_dump(exclude_none=True)
    if "panel_port" in update and not (1024 <= update["panel_port"] <= 65535):
        raise invalid_launch_args(f"端口越界: {update['panel_port']}")
    if not update:
        return ok({**_public(settings), "restart_required": False})
    new_settings = settings.model_copy(update=update)
    store.save(new_settings)
    restart_required = (
        "panel_port" in update and update["panel_port"] != settings.panel_port
    )
    return ok({**_public(new_settings), "restart_required": restart_required})


# ---------- 面板更新（API-015） ----------

@router.get("/update")
async def check_update(request: Request, settings: SettingsDep) -> dict[str, object]:
    updater = request.app.state.self_updater
    return ok(await updater.check_update(accel_enabled=settings.academic_accel_default))


@router.post("/update")
async def perform_update(request: Request, settings: SettingsDep) -> object:
    import asyncio

    from fastapi.responses import JSONResponse

    from app.api.envelope import ok as _ok

    updater = request.app.state.self_updater
    task = asyncio.create_task(
        updater.perform_update(accel_enabled=settings.academic_accel_default)
    )
    request.app.state.install_tasks["panel-update"] = task
    return JSONResponse(status_code=202, content=_ok({"phase": "downloading"}))
