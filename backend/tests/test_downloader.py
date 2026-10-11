"""下载器测试：本地 HTTP 服务器驱动（trust_env=False 绕过系统代理）。"""

from __future__ import annotations

import hashlib
import http.server
import socket
import threading
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from app.core.errors import AppError
from app.infra import downloader
from app.infra.downloader import (
    build_accel_env,
    download_file,
    fetch_json,
    parse_network_turbo,
)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture()
def static_server(tmp_path: Path) -> Iterator[tuple[str, Path]]:
    """本地静态文件服务器，返回 (base_url, serve_dir)。"""
    serve_dir = tmp_path / "www"
    serve_dir.mkdir()
    port = free_port()

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, directory=str(serve_dir), **kwargs)  # type: ignore[arg-type]

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}", serve_dir
    finally:
        server.shutdown()
        server.server_close()


def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(trust_env=False, follow_redirects=True)


async def test_download_success_with_sha256(
    static_server: tuple[str, Path], tmp_path: Path
) -> None:
    base, serve_dir = static_server
    payload = b"hello launchpad " * 4096  # ~64KB，跨多个 chunk
    (serve_dir / "pkg.bin").write_bytes(payload)
    sha = hashlib.sha256(payload).hexdigest()

    async with client() as c:
        path = await download_file(
            f"{base}/pkg.bin",
            dest_dir=tmp_path / "dl",
            filename="pkg.bin",
            expected_sha256=sha,
            client=c,
        )
    assert path.read_bytes() == payload
    assert not list(path.parent.glob("*.part"))


async def test_download_sha_mismatch(static_server: tuple[str, Path], tmp_path: Path) -> None:
    base, serve_dir = static_server
    (serve_dir / "bad.bin").write_bytes(b"actual content")
    dest = tmp_path / "dl2"
    async with client() as c:
        with pytest.raises(AppError) as ei:
            await download_file(
                f"{base}/bad.bin",
                dest_dir=dest,
                filename="bad.bin",
                expected_sha256="0" * 64,
                client=c,
            )
    assert ei.value.code == "checksum_mismatch"
    assert not (dest / "bad.bin").exists()
    assert not list(dest.glob("*.part"))


async def test_download_http_404(static_server: tuple[str, Path], tmp_path: Path) -> None:
    base, _serve_dir = static_server
    async with client() as c:
        with pytest.raises(AppError) as ei:
            await download_file(
                f"{base}/missing.bin",
                dest_dir=tmp_path / "dl3",
                filename="missing.bin",
                client=c,
            )
    assert ei.value.code == "download_failed"


async def test_download_progress_callback(static_server: tuple[str, Path], tmp_path: Path) -> None:
    base, serve_dir = static_server
    payload = b"x" * (256 * 1024)
    (serve_dir / "big.bin").write_bytes(payload)
    events: list[dict] = []

    async def cb(d: dict) -> None:
        events.append(d)

    async with client() as c:
        await download_file(
            f"{base}/big.bin",
            dest_dir=tmp_path / "dl4",
            filename="big.bin",
            client=c,
            on_progress=cb,
        )
    assert events, "进度回调未被调用"
    assert events[-1]["received"] == len(payload)
    speeds = [e["received"] for e in events]
    assert speeds == sorted(speeds)


async def test_download_disk_insufficient(
    static_server: tuple[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil as _shutil

    base, serve_dir = static_server
    (serve_dir / "huge.bin").write_bytes(b"y" * 1024)

    real_usage = _shutil.disk_usage

    def fake_usage(path: object) -> object:
        class U:
            total = 100 * 1024**3
            free = 10  # 几乎没空间
            used = 1

        return U()

    monkeypatch.setattr(downloader.shutil, "disk_usage", fake_usage)
    async with client() as c:
        with pytest.raises(AppError) as ei:
            await download_file(
                f"{base}/huge.bin",
                dest_dir=tmp_path / "dl5",
                filename="huge.bin",
                client=c,
            )
    assert ei.value.code == "disk_insufficient"
    assert real_usage  # 保留引用避免 lint 告警


async def test_fetch_json_ok_and_error(static_server: tuple[str, Path]) -> None:
    base, serve_dir = static_server
    (serve_dir / "index.json").write_text('{"versions": [1, 2]}', encoding="utf-8")
    async with client() as c:
        data = await fetch_json(f"{base}/index.json", client=c)
        assert data == {"versions": [1, 2]}

        with pytest.raises(AppError) as ei:
            await fetch_json(f"{base}/nope.json", client=c)
        assert ei.value.code == "download_failed"


def test_parse_network_turbo() -> None:
    text = """
export http_proxy=http://127.0.0.1:7890
export https_proxy=http://127.0.0.1:7890
export all_proxy=socks5://127.0.0.1:7891
export no_proxy='localhost,127.0.0.1'
"""
    env = parse_network_turbo(text)
    assert env["http_proxy"] == "http://127.0.0.1:7890"
    assert env["https_proxy"] == "http://127.0.0.1:7890"
    assert env["no_proxy"] == "localhost,127.0.0.1"


def test_build_accel_env_degrades(monkeypatch: pytest.MonkeyPatch) -> None:
    assert build_accel_env(False) is None
    # /etc/network_turbo 在 Windows 开发机必然不存在 → 优雅降级 None
    assert build_accel_env(True) is None
