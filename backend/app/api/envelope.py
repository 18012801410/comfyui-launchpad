"""统一响应包络：成功 {"ok": true, "data": …}，错误 {"ok": false, "error": {code, message}}。"""

from typing import Any


def ok(data: Any = None) -> dict[str, object]:
    return {"ok": True, "data": data}


def fail(code: str, message: str) -> dict[str, object]:
    return {"ok": False, "error": {"code": code, "message": message}}
