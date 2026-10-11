"""FastAPI 应用壳：装配路由、异常处理、鉴权与静态页面。"""

import logging
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse

from app import __version__
from app.api.auth import router as auth_router
from app.api.envelope import fail
from app.api.errors import AppError
from app.api.health import router as health_router
from app.api.panel import router as panel_router
from app.core.config import SettingsStore
from app.core.paths import LAYOUT, Layout

logger = logging.getLogger("launchpad")


def create_app(
    settings_store: SettingsStore | None = None,
    layout: Layout | None = None,
    extra_routers: list[APIRouter] | None = None,
) -> FastAPI:
    app = FastAPI(title="ComfyUI LaunchPad", version=__version__)
    app.state.settings_store = settings_store or SettingsStore(
        LAYOUT.state_dir / "config.json"
    )
    app.state.layout = layout or LAYOUT
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(panel_router)
    for r in extra_routers or []:
        app.include_router(r)

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status, content=fail(exc.code, exc.message)
        )

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
