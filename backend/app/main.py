"""FastAPI 应用壳：装配路由、静态页面与健康检查。"""

from fastapi import FastAPI

from app import __version__
from app.api.health import router as health_router


def create_app() -> FastAPI:
    app = FastAPI(title="ComfyUI LaunchPad", version=__version__)
    app.include_router(health_router)
    return app


app = create_app()
