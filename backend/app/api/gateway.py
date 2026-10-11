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
from fastapi.responses import JSONResponse, Response, StreamingResponse

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


def _forward_headers(headers: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in headers.items():
        if k.lower() in HOP_BY_HOP or k.lower() == "host":
            continue
        out[k] = v
    return out


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
    headers = _forward_headers(request.headers)
    headers["Host"] = f"127.0.0.1:{request.app.state.launch_store.load().listen_port}"

    client = httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(30, read=300))
    req = client.build_request(
        request.method, url, headers=headers, content=body
    )
    try:
        resp = await client.send(req, stream=True)
    except httpx.HTTPError:
        await client.aclose()
        return JSONResponse(
            status_code=502,
            content=fail("internal", "ComfyUI 未运行或不可达"),
        )

    resp_headers = _forward_headers(resp.headers)

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
        async with websockets.connect(
            target, max_size=None, open_timeout=10
        ) as upstream:
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

            done, _ = await asyncio.wait(
                [asyncio.create_task(pump_in()), asyncio.create_task(pump_out())],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in done:
                t.cancel()
    except (WebSocketDisconnect, websockets.exceptions.WebSocketException, OSError):
        pass
    finally:
        with contextlib.suppress(Exception):
            await websocket.close()
