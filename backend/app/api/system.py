"""系统状态路由（API-008）。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api.deps import require_token
from app.api.envelope import ok
from app.core.config import PanelSettings

router = APIRouter(prefix="/api/system")

SettingsDep = Annotated[PanelSettings, Depends(require_token)]


@router.get("/status")
def status(request: Request, _s: SettingsDep) -> dict[str, object]:
    collector = request.app.state.sysinfo
    supervisor = request.app.state.supervisor
    snap = collector.snapshot(comfy_process_state=supervisor.state.value)
    return ok(snap.to_dict())
