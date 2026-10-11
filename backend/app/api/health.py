"""健康检查：无鉴权，仅本机回环可访问（自升级健康检查用）。"""

from fastapi import APIRouter, Request

from app import __version__
from app.api.envelope import ok

router = APIRouter()

_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "testclient"}


@router.get("/api/health")
def health(request: Request) -> dict[str, object]:
    host = request.client.host if request.client else ""
    if host not in _LOOPBACK_HOSTS:
        return fail_403()
    return ok({"version": __version__, "uptime_s": 0})


def fail_403() -> dict[str, object]:
    return {"ok": False, "error": {"code": "path_forbidden", "message": "仅允许本机访问"}}
