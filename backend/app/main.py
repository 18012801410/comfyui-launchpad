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

PANEL_PREFIX = "/panel"


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

    def _workflows_channel_base() -> str:
        store: SettingsStore = app.state.settings_store
        settings = store.load()
        return settings.channels.workflows if settings else DEFAULT_WORKFLOWS_CHANNEL

    from app.domain.workflow_manager import DEFAULT_WORKFLOWS_CHANNEL, WorkflowManager

    app.state.workflow_manager = WorkflowManager(
        layout, channel_provider=_workflows_channel_base
    )

    def _self_channel_base() -> str:
        store: SettingsStore = app.state.settings_store
        settings = store.load()
        return settings.channels.self_channel if settings else DEFAULT_SELF_CHANNEL

    from app.domain.self_updater import DEFAULT_SELF_CHANNEL, SelfUpdater

    app.state.self_updater = SelfUpdater(
        layout,
        events=app.state.events,
        channel_provider=_self_channel_base,
        current_version_provider=lambda: __version__,
    )

    if sse_heartbeat is not None:
        app.state.sse_heartbeat = sse_heartbeat

    for r in extra_routers or []:
        app.include_router(r)

    # ---------- 路由编排（公网唯一入口架构，对标参考面板） ----------
    # 1) 面板自身 API 挂 /panel 前缀（/panel/api/...，带令牌）
    # 2) 面板 SPA 挂 /panel
    # 3) 网关占根路径：其余全部反向代理到本机 ComfyUI（HTTP+WS）
    app.include_router(health_router, prefix=PANEL_PREFIX)
    app.include_router(auth_router, prefix=PANEL_PREFIX)
    app.include_router(panel_router, prefix=PANEL_PREFIX)
    app.include_router(comfy_router, prefix=PANEL_PREFIX)
    app.include_router(system_router, prefix=PANEL_PREFIX)
    app.include_router(sse_router, prefix=PANEL_PREFIX)
    from app.api.plugins import router as plugins_router
    from app.api.versions import router as versions_router
    from app.api.workflows import router as workflows_router

    app.include_router(workflows_router, prefix=PANEL_PREFIX)
    app.include_router(versions_router, prefix=PANEL_PREFIX)
    app.include_router(plugins_router, prefix=PANEL_PREFIX)
    _mount_panel_spa(app)

    from app.api.gateway import router as gateway_router

    app.include_router(gateway_router)

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

    return app


def _mount_panel_spa(app: FastAPI) -> None:
    """面板 SPA 挂载于 /panel（存在构建产物时）。

    面板 API 路由已先行注册（/panel/api/...），挂载仅兜住 SPA 的 history 路由
    （/panel/versions 等 404 时回退 index.html）；根路径留给 ComfyUI 网关。
    """
    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if not dist.is_dir():
        return
    from fastapi.staticfiles import StaticFiles

    class SPAStaticFiles(StaticFiles):
        async def get_response(self, path: str, scope: dict):  # type: ignore[override,no-untyped-def]
            from starlette.exceptions import HTTPException

            try:
                resp = await super().get_response(path, scope)
            except HTTPException as exc:
                if exc.status_code == 404:
                    return await super().get_response("index.html", scope)
                raise
            if resp.status_code == 404:
                return await super().get_response("index.html", scope)
            return resp

    app.mount(PANEL_PREFIX, SPAStaticFiles(directory=dist, html=True), name="panel-spa")


app = create_app()
