"""自升级器测试：fake 渠道 + fake supervisor（切链接并输出 switched:）。"""

from __future__ import annotations

import hashlib
import http.server
import json
import socket
import threading
from pathlib import Path

import pytest

from app.core.errors import AppError
from app.domain.self_updater import SelfUpdater, read_current_panel_version
from app.domain.version_manager import make_tar_zst

CURRENT_VERSION = "2026.10.07"


def find_bash() -> str:
    """Windows 上 create_subprocess_exec("bash") 可能命中 WSL bash（无法处理 Windows 路径），
    需定位 Git Bash 的绝对路径。"""
    import os
    import shutil as _shutil

    if os.name != "nt":
        return "bash"
    bash = _shutil.which("bash")
    if bash and "system32" not in bash.lower():
        return bash
    git_exe = _shutil.which("git")
    if git_exe:
        for base in Path(git_exe).parents:
            candidate = base / "usr" / "bin" / "bash.exe"
            if candidate.is_file():
                return str(candidate)
    pytest.skip("未找到 Git Bash")


@pytest.fixture()
def panel_setup(tmp_path: Path, layout):
    """布置：假"已安装"面板（current 指向旧版本目录）+ fake supervisor + fake 渠道。"""
    # 已安装旧面板
    old_dir = layout.launchpad_dir / "releases" / CURRENT_VERSION
    old_dir.mkdir(parents=True)
    (old_dir / "version.json").write_text(
        json.dumps({"version": CURRENT_VERSION}), encoding="utf-8"
    )
    (old_dir / "backend" / "app").mkdir(parents=True)
    (old_dir / "backend" / "app" / "main.py").write_text("# old\n", encoding="utf-8")
    # current 指向旧版本（生产为符号链接；测试用目录副本等价可读）
    current = layout.launchpad_dir / "current"
    current.mkdir(exist_ok=True)
    (current / "version.json").write_text(
        json.dumps({"version": CURRENT_VERSION}), encoding="utf-8"
    )

    # fake supervisor：把"新版本目录"从 staging 落位到 releases/，切 current，输出 switched:
    supervisor = tmp_path / "fake_supervisor.sh"
    supervisor.write_text(
        f"""#!/usr/bin/env bash
set -e
NEW_DIR="$2"
V="$(basename "$NEW_DIR" | sed 's/\\.staging$//')"
mkdir -p "{layout.launchpad_dir / 'releases'}"
rm -rf "{layout.launchpad_dir / 'releases'}/$V"
mv "$NEW_DIR" "{layout.launchpad_dir / 'releases'}/$V"
# MSYS 下 ln -s 对真实目录语义不定，测试用 rm+cp 模拟"current 指向新版本"
rm -rf "{layout.launchpad_dir / 'current'}"
cp -r "{layout.launchpad_dir / 'releases'}/$V" "{layout.launchpad_dir / 'current'}"
echo "switched:$V"
""",
        encoding="utf-8",
        newline="\n",
    )
    return supervisor


@pytest.fixture()
def static_server(tmp_path: Path):
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


def publish_release(serve_dir: Path, base: str, version: str) -> None:
    """打包一个新面板发行版并发布索引。"""
    pkg_src = serve_dir / f"pkg-{version}"
    backend_main = pkg_src / "backend" / "app"
    backend_main.mkdir(parents=True, exist_ok=True)
    (backend_main / "main.py").write_text("# new panel\n", encoding="utf-8")
    (pkg_src / "version.json").write_text(
        json.dumps({"version": version}), encoding="utf-8"
    )
    archive = serve_dir / f"launchpad-{version}.tar.zst"
    make_tar_zst(pkg_src, archive)

    latest = serve_dir / "latest" / "download"
    latest.mkdir(parents=True, exist_ok=True)
    index = {
        "channel": "test",
        "updated_at": "2026-10-11T00:00:00Z",
        "releases": [
            {
                "version": version,
                "notes": f"升级到 {version}",
                "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                "url": f"{base}/launchpad-{version}.tar.zst",
                "published_at": "2026-10-11T00:00:00Z",
            }
        ],
    }
    (latest / "panel-index.json").write_text(json.dumps(index), encoding="utf-8")


async def test_check_update(panel_setup, static_server, layout) -> None:
    supervisor, (base, serve_dir) = panel_setup, static_server
    publish_release(serve_dir, base, "2026.10.10")
    updater = SelfUpdater(
        layout,
        supervisor_script=supervisor,
        channel_provider=lambda: base,
        current_version_provider=lambda: CURRENT_VERSION,
        bash_bin=find_bash(),
    )
    info = await updater.check_update()
    assert info["current_version"] == CURRENT_VERSION
    assert info["latest_version"] == "2026.10.10"
    assert info["available"] is True
    assert "升级" in info["notes"]


async def test_perform_update_success(
    panel_setup, static_server, layout
) -> None:
    supervisor, (base, serve_dir) = panel_setup, static_server
    publish_release(serve_dir, base, "2026.10.10")
    updater = SelfUpdater(
        layout,
        supervisor_script=supervisor,
        channel_provider=lambda: base,
        current_version_provider=lambda: CURRENT_VERSION,
        bash_bin=find_bash(),
    )
    result = await updater.perform_update()
    assert result["phase"] == "done"
    # current 已指向新版本目录，version.json 为新版
    assert read_current_panel_version(layout.launchpad_dir) == "2026.10.10"
    # staging 已清理
    assert not (layout.panel_releases_dir / "2026.10.10.staging").exists()


async def test_perform_update_already_latest(
    panel_setup, static_server, layout
) -> None:
    supervisor, (base, serve_dir) = panel_setup, static_server
    publish_release(serve_dir, base, CURRENT_VERSION)  # 同版本
    updater = SelfUpdater(
        layout,
        supervisor_script=supervisor,
        channel_provider=lambda: base,
        current_version_provider=lambda: CURRENT_VERSION,
        bash_bin=find_bash(),
    )
    with pytest.raises(AppError):
        await updater.perform_update()


async def test_rollback_when_supervisor_fails(
    panel_setup, static_server, layout, tmp_path: Path
) -> None:
    _supervisor, (base, serve_dir) = panel_setup, static_server
    publish_release(serve_dir, base, "2026.10.10")
    bad_supervisor = tmp_path / "bad_supervisor.sh"
    bad_supervisor.write_text(
        '#!/usr/bin/env bash\necho "switch-failed,rolling-back" >&2\nexit 1\n',
        encoding="utf-8",
        newline="\n",
    )
    updater = SelfUpdater(
        layout,
        supervisor_script=bad_supervisor,
        channel_provider=lambda: base,
        current_version_provider=lambda: CURRENT_VERSION,
        bash_bin=find_bash(),
    )
    with pytest.raises(AppError) as ei:
        await updater.perform_update()
    assert "回滚" in ei.value.message
    # 旧版本仍然在位
    assert read_current_panel_version(layout.launchpad_dir) == CURRENT_VERSION
