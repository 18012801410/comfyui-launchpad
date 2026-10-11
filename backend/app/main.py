"""FastAPI 应用壳：装配路由、异常处理、鉴权、领域单例与静态页面。"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse

from app import __version__
from app.api.auth import router as auth_router
from app.api.comfy import router as comfy_router
from app.api.envelope import fail
from app.api.errors import AppError
from app.api.health import router as health_router
from app.api.panel import router as panel_router
from app.api.sse import router as sse_router
from app.api.system import router as system_router
from app.core.config import SettingsStore
from app.core.events import EventBus
from app.core.paths import LAYOUT, Layout
from app.domain.launch_config import LaunchConfigStore
from app.domain.process_supervisor import ProcessSupervisor
from app.domain.sysinfo import SysinfoCollector

logger = logging.getLogger("launchpad")


def create_app(
    settings_store: SettingsStore | None = None,
    layout: Layout | None = None,
    extra_routers: list[APIRouter] | None = None,
    sse_heartbeat: float | None = None,
) -> FastAPI:
    layout = layout or LAYOUT

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # 启动对账（架构不变量 #3）：识别遗留 ComfyUI 进程
        snapshot = app.state.supervisor.reconcile()
        logger.info(
            "LaunchPad 启动，ComfyUI 对账状态: %s", snapshot.state.value
        )
        yield

    app = FastAPI(title="ComfyUI LaunchPad", version=__version__, lifespan=lifespan)

    # 领域单例
    app.state.layout = layout
    app.state.settings_store = settings_store or SettingsStore(
        layout.state_dir / "config.json"
    )
    app.state.events = EventBus()
    app.state.supervisor = ProcessSupervisor(layout, events=app.state.events)
    app.state.sysinfo = SysinfoCollector(layout)
    app.state.launch_store = LaunchConfigStore(layout.state_dir / "launch-config.json")
    app.state.install_tasks = {}

    def _is_comfy_running() -> bool:
        return app.state.supervisor.state.value not in ("stopped", "failed")

    def _versions_channel_base() -> str:
        store: SettingsStore = app.state.settings_store
        settings = store.load()
        return settings.channels.versions if settings else DEFAULT_VERSIONS_CHANNEL

    from app.domain.version_manager import DEFAULT_VERSIONS_CHANNEL, VersionManager

    app.state.version_manager = VersionManager(
        layout,
        events=app.state.events,
        is_running=_is_comfy_running,
        channel_provider=_versions_channel_base,
    )
    if sse_heartbeat is not None:
        app.state.sse_heartbeat = sse_heartbeat

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(panel_router)
    app.include_router(comfy_router)
    app.include_router(system_router)
    app.include_router(sse_router)
    from app.api.versions import router as versions_router

    app.include_router(versions_router)
    for r in extra_routers or []:
        app.include_router(r)

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content=fail(exc.code, exc.message))

    @app.exception_handler(Exception)
    async def unexpected_error_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        # 不向客户端泄露堆栈；完整堆栈进面板日志
        logger.exception("内部错误: %s", exc)
        return JSONResponse(
            status_code=500,
            content=fail("internal", "内部错误，请查看面板日志"),
        )

    _mount_static(app)
    return app


def _mount_static(app: FastAPI) -> None:
    """挂载前端构建产物（存在时）；API 路由优先于 SPA 回退。"""
    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if not dist.is_dir():
        return
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=dist, html=True), name="spa")


app = create_app()
