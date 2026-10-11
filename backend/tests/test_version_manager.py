"""版本管理器测试：本地渠道（索引+tar.zst 包）驱动安装/切换/删除全流程。"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.core.errors import AppError
from app.core.links import is_link
from app.domain.version_manager import (
    VersionManager,
    ensure_shared_links,
    make_tar_zst,
    resolve_current_version,
)


def make_version_package(tmp_path: Path, version: str) -> tuple[Path, str]:
    """构造一个合法版本包（main.py + requirements.txt），返回 (tar.zst 路径, sha256)。"""
    src = tmp_path / f"src-{version}"
    src.mkdir(parents=True, exist_ok=True)
    (src / "main.py").write_text(f"# comfyui {version}\n", encoding="utf-8")
    (src / "requirements.txt").write_text("torch\n", encoding="utf-8")
    archive = tmp_path / f"comfyui-{version}.tar.zst"
    make_tar_zst(src, archive)
    return archive, hashlib.sha256(archive.read_bytes()).hexdigest()


def write_index(
    serve_dir: Path, entries: list[dict], archives: dict[str, Path]
) -> None:
    """把索引与包发布到本地渠道目录；url 指向本地文件。索引须在 latest/download/ 下。"""
    import json

    for archive in archives.values():
        (serve_dir / archive.name).write_bytes(archive.read_bytes())
    latest = serve_dir / "latest" / "download"
    latest.mkdir(parents=True, exist_ok=True)
    index = {"channel": "test", "updated_at": "2026-10-11T00:00:00Z", "versions": entries}
    (latest / "versions-index.json").write_text(json.dumps(index), encoding="utf-8")


@pytest.fixture()
def channel(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, static_server_full):
    base, serve_dir = static_server_full
    pkg1, sha1 = make_version_package(tmp_path, "0.38.0")
    pkg2, sha2 = make_version_package(tmp_path, "0.39.0")
    write_index(
        serve_dir,
        [
            {
                "version": "0.38.0",
                "release_date": "2026-09-01",
                "torch_baseline": "2.4",
                "min_python": "3.10",
                "size_mb": pkg1.stat().st_size // (1024 * 1024) + 1,
                "sha256": sha1,
                "url": f"{base}/comfyui-0.38.0.tar.zst",
                "notes": "",
                "deprecated": False,
            },
            {
                "version": "0.39.0",
                "release_date": "2026-09-30",
                "torch_baseline": "2.4",
                "min_python": "3.10",
                "size_mb": pkg2.stat().st_size // (1024 * 1024) + 1,
                "sha256": sha2,
                "url": f"{base}/comfyui-0.39.0.tar.zst",
                "notes": "",
                "deprecated": False,
            },
        ],
        {"0.38.0": pkg1, "0.39.0": pkg2},
    )
    monkeypatch.setattr(
        "app.domain.version_manager.DEFAULT_VERSIONS_CHANNEL", base
    )
    return base


@pytest.fixture()
def static_server_full(tmp_path: Path):
    """与 test_downloader 的静态服务器同构（此处独立以免跨文件依赖）。"""
    import http.server
    import socket
    import threading

    serve_dir = tmp_path / "www"
    serve_dir.mkdir()
    port = socket.socket()
    port.bind(("127.0.0.1", 0))
    port_no = int(port.getsockname()[1])
    port.close()

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, directory=str(serve_dir), **kwargs)  # type: ignore[arg-type]

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", port_no), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{port_no}", serve_dir
    server.shutdown()
    server.server_close()


@pytest.fixture()
def manager(layout, channel) -> VersionManager:
    return VersionManager(layout, channel_provider=lambda: channel)


async def test_refresh_and_overview(manager: VersionManager) -> None:
    data = await manager.refresh_index()
    assert {e.version for e in data.versions} == {"0.38.0", "0.39.0"}

    index, cached_at, stale = manager.get_index()
    assert index is not None and cached_at and stale is False


async def test_install_switch_delete_flow(
    manager: VersionManager, layout
) -> None:
    await manager.refresh_index()
    info = await manager.install("0.39.0")
    assert info.status == "ready"
    vdir = layout.versions_dir / "0.39.0"
    assert (vdir / "main.py").is_file()
    # 共享布局链接建立（Windows 无权限时为 junction，is_link 均可识别）
    assert is_link(vdir / "models")
    assert is_link(vdir / "output")
    # staging 清理干净
    assert not list(layout.staging_dir.glob("*"))

    # 切换
    await manager.switch("0.39.0")
    assert resolve_current_version(layout) == "0.39.0"

    # 安装第二个版本并切换
    await manager.install("0.38.0")
    await manager.switch("0.38.0")
    assert resolve_current_version(layout) == "0.38.0"

    # 删除非当前版本 OK；删除当前版本被拒
    await manager.delete("0.39.0")
    assert not (layout.versions_dir / "0.39.0").exists()
    with pytest.raises(AppError) as ei:
        await manager.delete("0.38.0")
    assert ei.value.code == "version_in_use"


async def test_switch_running_guard(layout) -> None:
    await manager_refresh_stub(layout)
    mgr = VersionManager(layout, is_running=lambda: True)
    with pytest.raises(AppError) as ei:
        await mgr.switch("0.39.0")
    assert ei.value.code == "conflict_process_running"


async def test_delete_running_guard(manager: VersionManager, layout) -> None:
    await manager.refresh_index()
    await manager.install("0.39.0")
    await manager.switch("0.39.0")
    mgr_running = VersionManager(layout, is_running=lambda: True)
    with pytest.raises(AppError) as ei:
        await mgr_running.delete("0.39.0")
    assert ei.value.code == "conflict_process_running"


async def test_install_unknown_version(manager: VersionManager) -> None:
    await manager.refresh_index()
    with pytest.raises(AppError) as ei:
        await manager.install("9.9.9")
    assert ei.value.code == "version_not_installed"


async def test_install_without_index(manager: VersionManager) -> None:
    with pytest.raises(AppError) as ei:
        await manager.install("0.39.0")
    assert ei.value.code == "index_unavailable"


async def test_shared_links_function(layout, tmp_path: Path) -> None:
    fake_version = tmp_path / "vdir"
    fake_version.mkdir()
    (fake_version / "main.py").write_text("#", encoding="utf-8")
    ensure_shared_links(fake_version, layout)
    assert is_link(fake_version / "models")
    assert is_link(fake_version / "user")
    # 幂等
    ensure_shared_links(fake_version, layout)
    assert is_link(fake_version / "models")


async def manager_refresh_stub(layout) -> None:  # pragma: no cover - 测试辅助
    return None
