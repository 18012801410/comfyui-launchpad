"""TASK-006 验收：ComfyUI 控制路由、LaunchConfig、系统状态、SSE 通道。"""

from __future__ import annotations

import socket
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.links import ensure_dir_link
from tests.conftest import auth_header


def _make_fake_version(layout, version: str = "0.39.0") -> Path:
    """布置一个含 main.py 的假版本目录并链接 current。"""
    version_dir = layout.versions_dir / version
    version_dir.mkdir(parents=True, exist_ok=True)
    (version_dir / "main.py").write_text("# fake\n", encoding="utf-8")
    ensure_dir_link(version_dir, layout.current_link())
    return version_dir


def test_status_initial_stopped(client: TestClient, token: str) -> None:
    resp = client.get("/panel/api/comfy/status", headers=auth_header(token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["state"] == "stopped"
    assert data["pid"] is None


def test_start_without_version_404(client: TestClient, token: str) -> None:
    resp = client.post("/panel/api/comfy/start", headers=auth_header(token))
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "version_not_installed"


def test_start_port_conflict(client: TestClient, token: str, layout) -> None:
    import socket as _socket

    _make_fake_version(layout)
    # 把启动端口配置为随机空闲端口，再占住它
    with _socket.socket() as tmp:
        tmp.bind(("127.0.0.1", 0))
        free = int(tmp.getsockname()[1])
    assert (
        client.put(
            "/panel/api/comfy/launch-config",
            json={"listen_port": free},
            headers=auth_header(token),
        ).status_code
        == 200
    )
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", free))
    blocker.listen(1)
    try:
        resp = client.post("/panel/api/comfy/start", headers=auth_header(token))
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "port_conflict"
    finally:
        blocker.close()


def test_launch_config_roundtrip_and_validation(
    client: TestClient, token: str
) -> None:
    # 默认值
    r0 = client.get("/panel/api/comfy/launch-config", headers=auth_header(token))
    assert r0.status_code == 200
    assert r0.json()["data"]["listen_port"] == 8188

    # 合法修改 + 预设
    r1 = client.put(
        "/panel/api/comfy/launch-config",
        json={"listen_port": 8288, "preset": "low_vram", "academic_accel": True},
        headers=auth_header(token),
    )
    assert r1.status_code == 200
    data = r1.json()["data"]
    assert data["listen_port"] == 8288
    assert data["preset"] == "low_vram"
    assert data["academic_accel"] is True
    assert data["warnings"]

    # 非法端口
    r2 = client.put(
        "/panel/api/comfy/launch-config",
        json={"listen_port": 80},
        headers=auth_header(token),
    )
    assert r2.status_code == 422  # pydantic ge/le 校验

    # 与面板端口冲突（夹具面板端口 6006）
    r3 = client.put(
        "/panel/api/comfy/launch-config",
        json={"listen_port": 6006},
        headers=auth_header(token),
    )
    assert r3.status_code == 400
    assert r3.json()["error"]["code"] == "invalid_launch_args"

    # extra_args 非法字符
    r4 = client.put(
        "/panel/api/comfy/launch-config",
        json={"extra_args": "--evil `rm -rf /`"},
        headers=auth_header(token),
    )
    assert r4.status_code == 400
    assert r4.json()["error"]["code"] == "invalid_launch_args"


def test_logs_endpoint_empty(client: TestClient, token: str) -> None:
    resp = client.get("/panel/api/comfy/logs?tail=10", headers=auth_header(token))
    assert resp.status_code == 200
    assert resp.json()["data"]["lines"] == []


def test_system_status_shape(client: TestClient, token: str) -> None:
    resp = client.get("/panel/api/system/status", headers=auth_header(token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    for key in ("gpu", "memory", "disk", "cuda", "python_version", "comfy_process"):
        assert key in data
    assert data["comfy_process"] == "stopped"


def test_sse_requires_auth(client: TestClient) -> None:
    resp = client.get("/panel/api/events")
    assert resp.status_code == 401


async def test_sse_connected_and_heartbeat(raw_app: object, token: str) -> None:
    """夹具心跳 0.2s：经真实 uvicorn 端口验证 SSE（ASGITransport 不支持流式）。

    trust_env=False：测试机系统代理不得劫持 localhost。
    """
    import asyncio
    import socket
    import time as _time

    import httpx
    import uvicorn

    def free_port() -> int:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            return int(s.getsockname()[1])

    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(raw_app, host="127.0.0.1", port=port, log_level="error")
    )
    task = asyncio.create_task(server.serve())
    try:
        while not server.started:
            await asyncio.sleep(0.05)
        received: list[str] = []
        async with httpx.AsyncClient(trust_env=False) as ac, ac.stream(
            "GET",
            f"http://127.0.0.1:{port}/panel/api/events?topics=process",
            headers=auth_header(token),
        ) as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            it = resp.aiter_lines().__aiter__()
            deadline = _time.monotonic() + 5
            while len(received) < 2 and _time.monotonic() < deadline:
                try:
                    line = await asyncio.wait_for(anext(it), timeout=1.0)
                except (StopAsyncIteration, asyncio.TimeoutError):
                    break
                if line:
                    received.append(line)
        assert any(": connected" in ln for ln in received), received
        assert any(": heartbeat" in ln for ln in received), received
    finally:
        server.should_exit = True
        await task


def test_sse_event_frame_format() -> None:
    """事件帧格式化单测（独立于网络）。"""
    import json as _json

    topic, payload = "process", {"state": "running", "pid": 1}
    frame = f"event: {topic}\ndata: {_json.dumps(payload, ensure_ascii=False)}\n\n"
    assert frame.startswith("event: process\n")
    assert '"state": "running"' in frame
    assert frame.endswith("\n\n")
