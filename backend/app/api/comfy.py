"""ComfyUI 进程控制路由（API-004~007）。

路由层零业务规则：全部委托 ProcessSupervisor / LaunchConfig / version_manager。
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.api.deps import require_token
from app.api.envelope import ok
from app.api.errors import AppError
from app.core.config import PanelSettings
from app.domain.launch_config import LaunchConfig, LaunchConfigStore, Preset
from app.domain.process_supervisor import ProcessSupervisor, tcp_probe
from app.domain.version_manager import python_exe_for, resolve_current_dir, resolve_current_version

router = APIRouter(prefix="/api/comfy")

SettingsDep = Annotated[PanelSettings, Depends(require_token)]


def _supervisor(request: Request) -> ProcessSupervisor:
    sup: ProcessSupervisor = request.app.state.supervisor
    return sup


def _launch_store(request: Request) -> LaunchConfigStore:
    store: LaunchConfigStore = request.app.state.launch_store
    return store


@router.get("/status")
def status(request: Request, _s: SettingsDep) -> dict[str, object]:
    return ok(_supervisor(request).snapshot().to_dict())


@router.post("/start")
async def start(request: Request, settings: SettingsDep) -> dict[str, object]:
    sup = _supervisor(request)
    config = _launch_store(request).load()

    # 守卫顺序：版本优先于端口（语义更根本）
    current_dir = resolve_current_dir(request.app.state.layout)
    if current_dir is None:
        raise AppError("version_not_installed", "尚未安装任何 ComfyUI 版本", status=404)

    # 端口占用预检（FR-003）
    if tcp_probe(config.listen_port):
        raise AppError(
            "port_conflict",
            f"端口 {config.listen_port} 已被占用，请修改启动参数或释放端口",
            status=409,
        )
    version_dir = current_dir
    version_name = resolve_current_version(request.app.state.layout) or current_dir.name

    args = config.build_cli_args(panel_port=settings.panel_port)
    cmd = [str(python_exe_for(version_dir)), "main.py", *args]
    snap = await sup.start(cmd=cmd, workdir=version_dir, version=version_name)
    return ok(snap.to_dict())


@router.post("/stop")
async def stop(request: Request, _s: SettingsDep) -> dict[str, object]:
    snap = await _supervisor(request).stop()
    return ok(snap.to_dict())


@router.post("/restart")
async def restart(request: Request, settings: SettingsDep) -> dict[str, object]:
    sup = _supervisor(request)
    config = _launch_store(request).load()
    current_dir = resolve_current_dir(request.app.state.layout)
    if current_dir is None:
        raise AppError("version_not_installed", "尚未安装任何 ComfyUI 版本", status=404)
    version_dir = current_dir
    version_name = resolve_current_version(request.app.state.layout) or current_dir.name
    args = config.build_cli_args(panel_port=settings.panel_port)
    cmd = [str(python_exe_for(version_dir)), "main.py", *args]
    snap = await sup.restart(cmd=cmd, workdir=version_dir, version=version_name)
    return ok(snap.to_dict())


@router.get("/logs")
def logs(request: Request, _s: SettingsDep, tail: int = 300) -> dict[str, object]:
    lines = _supervisor(request).recent_logs(tail=max(1, min(tail, 2000)))
    return ok({"lines": lines})


class LaunchConfigBody(BaseModel):
    listen_port: int | None = Field(default=None, ge=1024, le=65535)
    listen_host: Literal["127.0.0.1", "0.0.0.0"] | None = None
    preset: Preset | None = None
    extra_args: str | None = None
    academic_accel: bool | None = None


@router.get("/launch-config")
def get_launch_config(request: Request, _s: SettingsDep) -> dict[str, object]:
    return ok(_launch_config_dict(_launch_store(request).load()))


def _launch_config_dict(config: LaunchConfig) -> dict[str, object]:
    return config.model_dump(mode="json")


@router.put("/launch-config")
def put_launch_config(
    body: LaunchConfigBody, request: Request, settings: SettingsDep
) -> dict[str, object]:
    store = _launch_store(request)
    current = store.load()
    update = body.model_dump(exclude_none=True)
    # 经 model_validate 重建以触发全部字段校验（model_copy 会绕过校验器）
    merged = {**current.model_dump(), **update}
    new_config = LaunchConfig.model_validate(merged)
    # build_cli_args 内含端口冲突校验（领域守卫）
    new_config.build_cli_args(panel_port=settings.panel_port)
    store.save(new_config)
    warnings: list[str] = []
    if new_config.preset != Preset.CUSTOM and new_config.preset != current.preset:
        warnings.append(f"预设 {new_config.preset.value} 将于下次启动时展开为对应参数")
    return ok({**_launch_config_dict(new_config), "warnings": warnings})
