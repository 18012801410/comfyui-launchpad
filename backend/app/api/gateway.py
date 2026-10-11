"""ComfyUI 网关：把本机 ComfyUI 反向代理到面板域名下（挂载于根路径）。

架构决策（对标参考面板）：公网唯一入口是面板端口；根路径代理 ComfyUI（其前端
使用绝对路径，零改写），面板自身 UI/API 收缩到 /panel/*。HTTP 走 httpx 流式，
WebSocket（/ws 进度推送）走 websockets 双向泵。
"""

from __future__ import annotations

import contextlib
from typing import Any

import httpx
import websockets
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, RedirectResponse, Response, StreamingResponse

from app.api.envelope import fail

router = APIRouter()

HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "content-encoding",
    "content-length",
}


def target_base(request: Request | WebSocket) -> str:
    port = request.app.state.launch_store.load().listen_port
    return f"http://127.0.0.1:{port}"


def _headers_kwarg() -> str:
    import inspect

    params = inspect.signature(websockets.connect).parameters
    if "additional_headers" in params:
        return "additional_headers"
    return "extra_headers"


def _forward_headers(headers: Any, target_base: str) -> dict[str, str]:
    """转发头：剔除逐跳头；改写 Origin/Referer 为后端视角。

    ComfyUI 有防 DNS 重绑定校验（Origin 的 host 与 Host 头不一致返回 403），
    经网关访问时必须把来源改写成后端自己的地址，否则前端全部 403。
    """
    out: dict[str, str] = {}
    origin_key = referer_key = None
    for k, v in headers.items():
        low = k.lower()
        if low in HOP_BY_HOP or low == "host":
            continue
        if low == "origin":
            origin_key = k
            continue
        if low == "referer":
            referer_key = k
            continue
        out[k] = v
    if origin_key is not None:
        out[origin_key] = target_base
    if referer_key is not None:
        out[referer_key] = target_base + "/"
    return out


@router.get("/", include_in_schema=False)
async def root_to_panel() -> Response:
    """根路径 = 产品入口：打开就是面板（302 到 /panel/）。

    ComfyUI 界面在 /index.html（其前端为 SPA，唯一入口页单独代理，其余
    绝对路径 /assets、/api、/ws 等由下方 catch-all 原样转发，零冲突）。
    """
    return RedirectResponse("/panel/", status_code=302)


@router.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
)
async def proxy_http(request: Request, path: str) -> Response:
    """根路径 HTTP 全量代理 → 本机 ComfyUI。"""
    base = target_base(request)
    url = f"{base}/{path}"
    if request.url.query:
        url += f"?{request.url.query}"
    body = await request.body()
    headers = _forward_headers(request.headers, base)
    headers["Host"] = f"127.0.0.1:{request.app.state.launch_store.load().listen_port}"

    client = httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(30, read=300))
    req = client.build_request(
        request.method, url, headers=headers, content=body
    )
    try:
        resp = await client.send(req, stream=True)
    except httpx.HTTPError:
        await client.aclose()
        # ComfyUI 未运行：浏览器访问引导去面板（面板才是产品入口），API 调用保留 JSON
        accept = request.headers.get("accept", "")
        if request.method == "GET" and "text/html" in accept:
            return RedirectResponse("/panel/", status_code=302)
        return JSONResponse(
            status_code=502,
            content=fail("internal", "ComfyUI 未运行或不可达，请先在面板中启动"),
        )

    resp_headers = _forward_headers(resp.headers, base)

    async def stream() -> Any:
        try:
            async for chunk in resp.aiter_bytes():
                yield chunk
        finally:
            await resp.aclose()
            await client.aclose()

    return StreamingResponse(
        stream(), status_code=resp.status_code, headers=resp_headers
    )


@router.websocket("/ws")
@router.websocket("/{ws_path:path}")
async def proxy_ws(websocket: WebSocket, ws_path: str = "") -> None:
    """WebSocket 双向代理（ComfyUI 进度推送 /ws?clientId=…）。"""
    base = target_base(websocket)
    query = f"?{websocket.url.query}" if websocket.url.query else ""
    target = f"ws://127.0.0.1:{base.split(':')[-1]}/{ws_path}{query}"
    await websocket.accept()
    try:
        ws_kwargs: dict[str, Any] = {"max_size": None, "open_timeout": 10}
        # websockets 版本兼容：旧版参数 extra_headers，新版(≥14)改名 additional_headers
        ws_kwargs[_headers_kwarg()] = {"Origin": base}
        async with websockets.connect(target, **ws_kwargs) as upstream:
            import asyncio

            async def pump_in() -> None:
                try:
                    async for msg in upstream:
                        if isinstance(msg, str):
                            await websocket.send_text(msg)
                        else:
                            await websocket.send_bytes(msg)
                except Exception:  # noqa: BLE001
                    pass

            async def pump_out() -> None:
                try:
                    while True:
                        msg = await websocket.receive()
                        if msg.get("type") == "websocket.disconnect":
                            break
                        data = msg.get("data") or msg.get("bytes")
                        if data is None:
                            continue
                        if isinstance(data, str):
                            await upstream.send(data)
                        else:
                            await upstream.send(data)
                except Exception:  # noqa: BLE001
                    pass

            tasks = [
                asyncio.create_task(pump_in()),
                asyncio.create_task(pump_out()),
            ]
            _done, pending = await asyncio.wait(
                tasks, return_when=asyncio.FIRST_COMPLETED
            )
            # 关键：取消未完成方向的泵（孤儿任务会导致连接反复断开重连）
            for t in pending:
                t.cancel()
            with contextlib.suppress(Exception):
                await asyncio.gather(*pending, return_exceptions=True)
    except (WebSocketDisconnect, websockets.exceptions.WebSocketException, OSError):
        pass
    finally:
        with contextlib.suppress(Exception):
            await websocket.close()
