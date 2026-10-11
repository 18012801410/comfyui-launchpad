"""版本管理器：索引拉取/缓存、安装（原子）、符号链接切换、删除、共享布局。

不变量（docs/DOMAIN_MODEL.md「ComfyVersion」）：
- current 当且仅当指向含 main.py 的 ready 实例；
- 任何时刻至多一个 installing 任务；
- 进程运行中禁止切换/删除；
- 实例内 models/output/input/user 恒为指向共享目录的链接；
- 一切目录变更走 staging + 原子 rename（架构不变量 #2）。
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tarfile
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import zstandard
from pydantic import BaseModel, Field

from app.core.config import read_json_with_backup, write_json_atomic
from app.core.errors import AppError
from app.core.events import EventBus
from app.core.links import ensure_dir_link, remove_dir_link
from app.core.paths import Layout
from app.infra.downloader import build_accel_env, download_file, fetch_json

TOPIC_VERSIONS = "versions"
TOPIC_DOWNLOADS = "downloads"
DEFAULT_VERSIONS_CHANNEL = (
    "https://github.com/REPLACE_ME/launchpad-versions/releases"
)


class IndexEntry(BaseModel):
    version: str
    release_date: str = ""
    torch_baseline: str = ""
    min_python: str = "3.10"
    python_abi: str = ""  # 空表示不限制；非空须与实例 Python 大版本一致（venv 不可迁移）
    size_mb: int = 0
    sha256: str = ""
    url: str
    notes: str = ""
    deprecated: bool = False


class IndexData(BaseModel):
    channel: str = "launchpad-versions"
    updated_at: str = ""
    versions: list[IndexEntry] = Field(default_factory=list)


class InstalledInfo(BaseModel):
    version: str
    installed_at: str | None = None
    disk_size_mb: float | None = None
    status: str = "ready"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _min_python_ok(min_python: str) -> bool:
    try:
        parts = tuple(int(p) for p in min_python.split(".")[:2])
        return sys.version_info[:2] >= parts
    except ValueError:
        return True


def index_url_from_channel(channel_base: str) -> str:
    """渠道仓库基址 → 索引 URL（GitHub Releases 约定）。"""
    return f"{channel_base.rstrip('/')}/latest/download/versions-index.json"


def safe_extract_tar_zst(archive: Path, dest: Path) -> None:
    """安全解压 tar.zst（filter=data 防路径穿越；旧 Python 降级）。"""
    dctx = zstandard.ZstdDecompressor()
    with (
        archive.open("rb") as fr,
        dctx.stream_reader(fr) as zr,
        tarfile.open(fileobj=zr, mode="r|") as tar,
    ):
        try:
            tar.extractall(dest, filter="data")  # noqa: S202 - filter=data 已消毒
        except TypeError:
            tar.extractall(dest)  # pragma: no cover - py<3.11.4


def make_tar_zst(src_dir: Path, out_path: Path) -> None:
    """打包目录 → tar.zst（测试与打包脚本共用逻辑）。"""
    cctx = zstandard.ZstdCompressor()
    with (
        out_path.open("wb") as fw,
        cctx.stream_writer(fw) as zw,
        tarfile.open(fileobj=zw, mode="w|") as tar,
    ):
        for item in sorted(src_dir.iterdir()):
            tar.add(str(item), arcname=item.name)


def ensure_shared_links(version_dir: Path, layout: Layout) -> None:
    """版本目录内建立共享数据布局链接（FR-007）。"""
    pairs = [
        (layout.shared_models, version_dir / "models"),
        (layout.shared_output, version_dir / "output"),
        (layout.shared_input, version_dir / "input"),
        (layout.shared_user, version_dir / "user"),
    ]
    for target, link in pairs:
        # 已存在的真实目录先改名保留（例如包内自带空目录）
        if link.exists() and not remove_dir_link_if_link(link):
            backup = link.with_name(link.name + ".bundled")
            if backup.exists():
                shutil.rmtree(backup, ignore_errors=True)
            link.rename(backup)
        ensure_dir_link(target, link)


def remove_dir_link_if_link(link: Path) -> bool:
    """若是链接则删除并返回 True；普通目录不动。"""
    if link.is_symlink() or (
        sys.platform == "win32" and link.exists() and _is_reparse(link)
    ):
        remove_dir_link(link)
        return True
    return False


def _is_reparse(link: Path) -> bool:
    try:
        return os.path.realpath(link) != str(link)
    except OSError:
        return False


class VersionManager:
    def __init__(
        self,
        layout: Layout,
        events: EventBus | None = None,
        is_running: Callable[[], bool] | None = None,
        channel_provider: Callable[[], str] | None = None,
    ) -> None:
        self._layout = layout
        self._events = events or EventBus()
        self._is_running = is_running or (lambda: False)
        self._channel_provider = channel_provider or (lambda: DEFAULT_VERSIONS_CHANNEL)
        self._install_lock = asyncio.Lock()
        self._installing_version: str | None = None
        self._index_cache_path = layout.state_dir / "versions-index-cache.json"
        self._state_path = layout.state_dir / "versions-state.json"

    # ---------- 索引 ----------

    async def refresh_index(self, accel_enabled: bool = False) -> IndexData:
        accel_env = await asyncio.to_thread(build_accel_env, accel_enabled)
        url = index_url_from_channel(self._channel_provider())
        try:
            raw = await fetch_json(url, accel_env=accel_env)
        except AppError as exc:
            raise AppError(
                "index_unavailable",
                f"版本索引不可达：{exc.message}",
                status=502,
            ) from exc
        data = IndexData.model_validate(raw)
        write_json_atomic(
            self._index_cache_path,
            {"cached_at": _utcnow_iso(), **data.model_dump()},
        )
        return data

    def get_index(self) -> tuple[IndexData | None, str | None, bool]:
        """返回 (索引或 None, cached_at, stale)。缓存缺失且无网时 stale=True 语义由调用方组合。"""
        if not self._index_cache_path.exists():
            return None, None, True
        try:
            raw = read_json_with_backup(self._index_cache_path)
            data = IndexData.model_validate(raw)
            cached_at = raw.get("cached_at")
            return data, str(cached_at) if cached_at else None, False
        except Exception:  # noqa: BLE001 - 缓存损坏按无缓存处理
            return None, None, True

    # ---------- 安装 ----------

    def is_installing(self) -> bool:
        return self._installing_version is not None

    async def install(
        self,
        version: str,
        accel_enabled: bool = False,
        on_progress: Callable[[dict[str, Any]], Any] | None = None,
    ) -> InstalledInfo:
        if self._installing_version is not None:
            raise AppError(
                "conflict_install_in_progress",
                f"已有安装任务进行中（{_installing_label(self._installing_version)}）",
                status=409,
            )
        entries, _, _ = self.get_index()
        if entries is None:
            raise AppError("index_unavailable", "版本索引不可用，请先刷新索引", status=502)
        entry = next((e for e in entries.versions if e.version == version), None)
        if entry is None:
            raise AppError("version_not_installed", f"渠道中不存在版本 {version}", status=404)
        if not _min_python_ok(entry.min_python):
            raise AppError(
                "version_not_ready",
                f"该版本要求 Python ≥ {entry.min_python}，当前 {sys.version.split()[0]}",
                status=400,
            )
        if entry.python_abi and entry.python_abi != f"{sys.version_info[0]}.{sys.version_info[1]}":
            raise AppError(
                "version_not_ready",
                f"该版本包为 Python {entry.python_abi} ABI 构建，"
                f"与当前实例 Python {sys.version_info[0]}.{sys.version_info[1]} 不兼容"
                "（包内 venv 不可跨 ABI 迁移）",
                status=400,
            )

        async with self._install_lock:
            self._installing_version = version
            try:
                info = await self._do_install(entry, accel_enabled, on_progress)
                return info
            finally:
                self._installing_version = None

    async def _do_install(
        self,
        entry: IndexEntry,
        accel_enabled: bool,
        on_progress: Callable[[dict[str, Any]], Any] | None,
    ) -> InstalledInfo:
        layout = self._layout
        layout.ensure()
        staging_pkg = layout.staging_dir / f"comfyui-{entry.version}.tar.zst"
        staging_dir = layout.staging_dir / entry.version
        shutil.rmtree(staging_dir, ignore_errors=True)
        staging_pkg.unlink(missing_ok=True)
        staging_dir.mkdir(parents=True, exist_ok=True)

        accel_env = await asyncio.to_thread(build_accel_env, accel_enabled)
        loop = asyncio.get_event_loop()

        async def progress_cb(d: dict[str, Any]) -> None:
            self._events.publish(
                TOPIC_DOWNLOADS, {"task": f"install:{entry.version}", **d}
            )
            if on_progress is not None:
                on_progress(d)

        started = time.monotonic()
        await download_file(
            entry.url,
            dest_dir=layout.staging_dir,
            filename=staging_pkg.name,
            expected_sha256=entry.sha256 or None,
            expected_size=entry.size_mb * 1024 * 1024 or None,
            accel_env=accel_env,
            on_progress=progress_cb,
        )
        await loop.run_in_executor(None, safe_extract_tar_zst, staging_pkg, staging_dir)
        staging_pkg.unlink(missing_ok=True)

        # 结构校验：包内须有 main.py（根目录或单层子目录）
        src = staging_dir if (staging_dir / "main.py").is_file() else _single_subdir(staging_dir)
        if src is None:
            shutil.rmtree(staging_dir, ignore_errors=True)
            raise AppError(
                "version_not_ready", f"版本包结构异常（缺少 main.py）: {entry.version}", status=502
            )

        # 建共享布局 → 原子 rename 到正式路径
        ensure_shared_links(src, layout)
        final_dir = layout.versions_dir / entry.version
        if final_dir.exists():
            # 重装（修复式覆盖）：先移走旧目录
            old = layout.versions_dir / f"{entry.version}.old"
            shutil.rmtree(old, ignore_errors=True)
            os.replace(final_dir, old)
            shutil.rmtree(old, ignore_errors=True)
        os.replace(src, final_dir)
        shutil.rmtree(staging_dir, ignore_errors=True)

        disk_mb = _dir_size_mb(final_dir)
        info = InstalledInfo(
            version=entry.version,
            installed_at=_utcnow_iso(),
            disk_size_mb=disk_mb,
            status="ready",
        )
        self._mark_installed(info)
        self._events.publish(
            TOPIC_VERSIONS, {"kind": "installed", "version": entry.version}
        )
        self._log(f"版本 {entry.version} 安装完成，用时 {time.monotonic() - started:.1f}s")
        return info

    # ---------- 切换 / 删除 ----------

    def current_version(self) -> str | None:
        current = resolve_current_version(self._layout)
        return current

    async def switch(self, version: str) -> str:
        self._assert_not_running("切换")
        installed = self.installed_map()
        info = installed.get(version)
        if info is None or info.status != "ready":
            raise AppError("version_not_installed", f"版本 {version} 未安装或未就绪", status=404)
        link = self._layout.current_link()
        remove_dir_link_if_link(link)
        ensure_dir_link(self._layout.versions_dir / version, link)
        self._events.publish(TOPIC_VERSIONS, {"kind": "switched", "version": version})
        self._log(f"当前版本已切换为 {version}")
        return version

    async def delete(self, version: str) -> None:
        self._assert_not_running("删除")
        if self.current_version() == version:
            raise AppError("version_in_use", f"版本 {version} 是当前版本，禁止删除", status=409)
        target = safe_version_dir(self._layout, version)
        shutil.rmtree(target, ignore_errors=True)
        self._mark_removed(version)
        self._events.publish(TOPIC_VERSIONS, {"kind": "removed", "version": version})

    def _assert_not_running(self, action: str) -> None:
        if self._is_running():
            raise AppError(
                "conflict_process_running",
                f"ComfyUI 运行中，禁止{action}版本；请先停止进程",
                status=409,
            )

    # ---------- 已装清单 ----------

    def installed_map(self) -> dict[str, InstalledInfo]:
        raw: dict[str, Any] = {}
        if self._state_path.exists():
            try:
                raw = read_json_with_backup(self._state_path)
            except Exception:  # noqa: BLE001
                raw = {}
        installed: dict[str, InstalledInfo] = {}
        state_map = raw.get("installed", {})
        if self._layout.versions_dir.is_dir():
            for child in sorted(self._layout.versions_dir.iterdir()):
                if not child.is_dir() or child.name.startswith(".") or child.name.endswith(".old"):
                    continue
                if not (child / "main.py").is_file():
                    continue
                meta = state_map.get(child.name, {})
                installed[child.name] = InstalledInfo(
                    version=child.name,
                    installed_at=meta.get("installed_at"),
                    disk_size_mb=meta.get("disk_size_mb"),
                    status="ready",
                )
        return installed

    def _mark_installed(self, info: InstalledInfo) -> None:
        raw: dict[str, Any] = {}
        if self._state_path.exists():
            try:
                raw = read_json_with_backup(self._state_path)
            except Exception:  # noqa: BLE001
                raw = {}
        installed = raw.get("installed", {})
        installed[info.version] = info.model_dump()
        write_json_atomic(self._state_path, {"installed": installed})

    def _mark_removed(self, version: str) -> None:
        if not self._state_path.exists():
            return
        raw_obj: dict[str, Any] = read_json_with_backup(self._state_path)
        installed: dict[str, Any] = dict(raw_obj.get("installed", {}))
        installed.pop(version, None)
        write_json_atomic(self._state_path, {"installed": installed})

    def _log(self, message: str) -> None:
        self._events.publish("logs", {"source": "panel", "line": message})


# ---------- 模块级工具（含 resolve_current，供进程路由使用） ----------

def _installing_label(version: str) -> str:
    return f"install:{version}"


def _single_subdir(staging_dir: Path) -> Path | None:
    children = [c for c in staging_dir.iterdir() if c.is_dir()]
    if len(children) == 1 and (children[0] / "main.py").is_file():
        return children[0]
    return None


def _dir_size_mb(path: Path) -> float:
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            continue
    return round(total / (1024 * 1024), 1)


def resolve_current_version(layout: Layout) -> str | None:
    link = layout.current_link()
    if not link.exists():
        return None
    target = Path(os.path.realpath(link))
    if not target.is_dir() or not (target / "main.py").is_file():
        return None
    return target.name


def resolve_current_dir(layout: Layout) -> Path | None:
    link = layout.current_link()
    if not link.exists():
        return None
    target = Path(os.path.realpath(link))
    if not target.is_dir() or not (target / "main.py").is_file():
        return None
    return target


def python_exe_for(version_dir: Path) -> Path:
    """版本内独立 venv 的解释器；缺失回退面板自身解释器。"""
    sub = "Scripts" if sys.platform == "win32" else "bin"
    exe = "python.exe" if sys.platform == "win32" else "python"
    candidate = version_dir / "venv" / sub / exe
    return candidate if candidate.is_file() else Path(sys.executable)


def safe_version_dir(layout: Layout, version: str) -> Path:
    """版本目录白名单校验（防目录穿越）。"""
    from app.core.paths import PathOutsideWhitelist, safe_resolve

    try:
        resolved = safe_resolve(layout.versions_dir, version)
    except PathOutsideWhitelist as exc:
        raise AppError("path_forbidden", str(exc), status=403) from exc
    return resolved
