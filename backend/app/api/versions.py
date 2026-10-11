"""版本管理路由（API-009/010）。安装为后台任务，进度走 SSE downloads 主题。"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.deps import require_token
from app.api.envelope import ok
from app.api.errors import AppError
from app.core.config import PanelSettings
from app.domain.version_manager import VersionManager

router = APIRouter(prefix="/api/versions")

SettingsDep = Annotated[PanelSettings, Depends(require_token)]


def _manager(request: Request) -> VersionManager:
    mgr: VersionManager = request.app.state.version_manager
    return mgr


@router.get("")
async def overview(request: Request, settings: SettingsDep) -> dict[str, object]:
    mgr = _manager(request)
    index, cached_at, stale = mgr.get_index()
    installed = mgr.installed_map()
    current = mgr.current_version()

    available: list[dict[str, Any]] = []
    if index is not None:
        for entry in index.versions:
            available.append(
                {
                    **entry.model_dump(),
                    "installed": entry.version in installed,
                }
            )
    index_unreachable = index is None
    return ok(
        {
            "current": current,
            "installed": [i.model_dump() for i in installed.values()],
            "available": available,
            "index_cached_at": cached_at,
            "index_stale": stale,
            "index_unreachable": index_unreachable,
        }
    )


@router.post("/refresh")
async def refresh(request: Request, settings: SettingsDep) -> dict[str, object]:
    mgr = _manager(request)
    try:
        data = await mgr.refresh_index(accel_enabled=settings.academic_accel_default)
    except AppError:
        raise
    return ok({"updated_at": data.updated_at, "count": len(data.versions)})


@router.post("/{version}/install")
async def install(version: str, request: Request, settings: SettingsDep) -> object:
    mgr = _manager(request)
    # 202 + 后台任务；进度经 SSE downloads 主题推送
    if mgr.is_installing():
        raise AppError(
            "conflict_install_in_progress", "已有安装任务进行中", status=409
        )
    task = asyncio.create_task(
        mgr.install(version, accel_enabled=settings.academic_accel_default)
    )
    request.app.state.install_tasks[version] = task

    def _cleanup(t: asyncio.Task[object]) -> None:
        request.app.state.install_tasks.pop(version, None)

    task.add_done_callback(_cleanup)
    return JSONResponse(status_code=202, content=ok({"task": f"install:{version}"}))


@router.post("/{version}/switch")
async def switch(
    version: str, request: Request, settings: SettingsDep
) -> dict[str, object]:
    mgr = _manager(request)
    switched = await mgr.switch(version)
    return ok({"current": switched})


@router.delete("/{version}")
async def delete_version(
    version: str, request: Request, settings: SettingsDep
) -> dict[str, object]:
    mgr = _manager(request)
    await mgr.delete(version)
    return ok({"removed": version})
