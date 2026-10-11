"""工作流管理路由（API-013/014）。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, UploadFile
from pydantic import BaseModel

from app.api.deps import require_token
from app.api.envelope import ok
from app.core.config import PanelSettings
from app.domain.workflow_manager import WorkflowManager

router = APIRouter(prefix="/api/workflows")

SettingsDep = Annotated[PanelSettings, Depends(require_token)]


def _manager(request: Request) -> WorkflowManager:
    mgr: WorkflowManager = request.app.state.workflow_manager
    return mgr


@router.get("")
def list_items(request: Request, _s: SettingsDep) -> dict[str, object]:
    items = _manager(request).list_items()
    return ok({"items": [i.model_dump() for i in items]})


@router.get("/library")
async def library(
    request: Request,
    settings: SettingsDep,
    refresh: bool = Query(default=False),
) -> dict[str, object]:
    mgr = _manager(request)
    if refresh:
        index = await mgr.refresh_library(
            accel_enabled=settings.academic_accel_default
        )
        payload = {
            "workflows": [w.model_dump() for w in index.workflows],
            "cached_at": None,
            "stale": False,
        }
        return ok(payload)
    index, cached_at, stale = mgr.get_library()
    return ok(
        {
            "workflows": [w.model_dump() for w in index.workflows] if index else [],
            "cached_at": cached_at,
            "stale": stale,
        }
    )


@router.post("/refresh-library")
async def refresh_library(request: Request, settings: SettingsDep) -> dict[str, object]:
    index = await _manager(request).refresh_library(
        accel_enabled=settings.academic_accel_default
    )
    return ok({"updated_at": index.updated_at, "count": len(index.workflows)})


class ImportBody(BaseModel):
    slug: str


@router.post("/import")
async def import_workflow(
    body: ImportBody, request: Request, settings: SettingsDep
) -> dict[str, object]:
    item = await _manager(request).import_official(
        body.slug, accel_enabled=settings.academic_accel_default
    )
    return ok(item.model_dump())


@router.post("/upload")
async def upload_workflow(
    request: Request, _s: SettingsDep, file: UploadFile
) -> dict[str, object]:
    if file.filename is None:
        from app.api.errors import invalid_workflow

        raise invalid_workflow("缺少文件名")
    content = await file.read()
    item = _manager(request).save_upload(file.filename, content)
    return ok(item.model_dump())


@router.delete("/{workflow_id}")
def delete_workflow(
    workflow_id: str, request: Request, _s: SettingsDep
) -> dict[str, object]:
    _manager(request).delete(workflow_id)
    return ok({"removed": workflow_id})
