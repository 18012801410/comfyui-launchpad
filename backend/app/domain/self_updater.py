"""面板自升级器：检查更新 → 下载 → staging 解压 → supervisor switch 接管。

不变量（docs/DOMAIN_MODEL.md「PanelRelease」）：
- releases/ 始终保留上一成功版本目录（supervisor 清理至最近 2 个）；
- 升级任何阶段失败回滚到上一 ready 目录；config 与令牌位于数据盘跨版本保留；
- 阶段经 SSE panel_event 推送：downloading → staging → switching → done | rolled_back。
"""

from __future__ import annotations

import asyncio
import shutil
import tarfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import zstandard
from pydantic import BaseModel, Field

from app.core.errors import AppError
from app.core.events import EventBus
from app.core.paths import Layout
from app.infra.downloader import build_accel_env, download_file, fetch_json

TOPIC_PANEL = "panel"
DEFAULT_SELF_CHANNEL = (
    "https://github.com/REPLACE_ME/launchpad-panel/releases"
)


class PanelRelease(BaseModel):
    version: str
    notes: str = ""
    sha256: str = ""
    url: str = ""
    published_at: str = ""


class PanelIndex(BaseModel):
    channel: str = "launchpad-panel"
    updated_at: str = ""
    releases: list[PanelRelease] = Field(default_factory=list)


def index_url_from_channel(channel_base: str) -> str:
    return f"{channel_base.rstrip('/')}/latest/download/panel-index.json"


def read_current_panel_version(launchpad_dir: Path) -> str:
    meta = launchpad_dir / "current" / "version.json"
    try:
        import json

        return str(json.loads(meta.read_text(encoding="utf-8")).get("version", ""))
    except (OSError, ValueError):
        return ""


def _is_newer(candidate: str, current: str) -> bool:
    def parts(v: str) -> list[int]:
        out: list[int] = []
        for seg in v.replace("v", "").split("."):
            num = "".join(ch for ch in seg if ch.isdigit())
            out.append(int(num) if num else 0)
        return out

    try:
        return parts(candidate) > parts(current)
    except Exception:  # noqa: BLE001
        return candidate != current


class SelfUpdater:
    def __init__(
        self,
        layout: Layout,
        events: EventBus | None = None,
        channel_provider: Callable[[], str] | None = None,
        supervisor_script: Path | None = None,
        current_version_provider: Callable[[], str] | None = None,
        bash_bin: str = "bash",
    ) -> None:
        self._layout = layout
        self._events = events or EventBus()
        self._channel_provider = channel_provider or (
            lambda: "https://github.com/REPLACE_ME/launchpad-panel/releases"
        )
        self._supervisor = supervisor_script or (
            layout.launchpad_dir / "supervisor.sh"
        )
        self._bash = bash_bin
        self._current_version = current_version_provider or (
            lambda: read_current_panel_version(layout.launchpad_dir)
        )
        self._busy = False

    def is_busy(self) -> bool:
        return self._busy

    async def check_update(self, accel_enabled: bool = False) -> dict[str, Any]:
        accel_env = await asyncio.to_thread(build_accel_env, accel_enabled)
        url = index_url_from_channel(self._channel_provider())
        try:
            raw = await fetch_json(url, accel_env=accel_env)
        except AppError as exc:
            raise AppError(
                "index_unavailable", f"更新索引不可达：{exc.message}", status=502
            ) from exc
        index = PanelIndex.model_validate(raw)
        current = self._current_version()
        latest = index.releases[0] if index.releases else None
        return {
            "current_version": current,
            "latest_version": latest.version if latest else current,
            "available": bool(latest and _is_newer(latest.version, current)),
            "notes": latest.notes if latest else "",
            "checking": False,
        }

    async def perform_update(
        self, release_version: str | None = None, accel_enabled: bool = False
    ) -> dict[str, Any]:
        if self._busy:
            raise AppError("conflict_install_in_progress", "已有升级任务进行中", status=409)
        self._busy = True
        try:
            return await self._do_update(release_version, accel_enabled)
        finally:
            self._busy = False

    async def _do_update(
        self, release_version: str | None, accel_enabled: bool
    ) -> dict[str, Any]:
        layout = self._layout
        layout.ensure()
        accel_env = await asyncio.to_thread(build_accel_env, accel_enabled)

        # 1. 查询渠道
        self._emit("downloading")
        url = index_url_from_channel(self._channel_provider())
        try:
            raw = await fetch_json(url, accel_env=accel_env)
        except AppError as exc:
            self._emit("rolled_back", exc.message)
            raise
        index = PanelIndex.model_validate(raw)
        release = index.releases[0] if index.releases else None
        if release is None or (release_version and release.version != release_version):
            self._emit("rolled_back", "渠道中没有目标版本")
            raise AppError("download_failed", "渠道中没有目标版本", status=404)
        if not _is_newer(release.version, self._current_version()):
            self._emit("rolled_back", f"已是最新版本 {self._current_version()}")
            raise AppError(
                "download_failed", f"已是最新版本 {self._current_version()}", status=400
            )

        # 2. 下载 + 解压到 staging
        staging_root = layout.panel_releases_dir / f"{release.version}.staging"
        shutil.rmtree(staging_root, ignore_errors=True)
        staging_root.mkdir(parents=True, exist_ok=True)
        try:
            await download_file(
                release.url,
                dest_dir=layout.panel_releases_dir,
                filename=f"launchpad-{release.version}.tar.zst",
                expected_sha256=release.sha256 or None,
                accel_env=accel_env,
                on_progress=_emit_progress(self._events, f"panel:{release.version}"),
            )
            self._emit("staging")
            archive = layout.panel_releases_dir / f"launchpad-{release.version}.tar.zst"
            await asyncio.to_thread(_extract, archive, staging_root)
            archive.unlink(missing_ok=True)

            if not (staging_root / "backend" / "app" / "main.py").is_file():
                raise AppError("checksum_mismatch", "发行包结构异常", status=502)

            # 3. supervisor switch 接管：接收 staging 目录，
            #    落位→停旧→切换→健康检查→失败回滚（健康检查在 supervisor 内完成）
            self._emit("switching")
            proc = await asyncio.create_subprocess_exec(
                self._bash,
                str(self._supervisor),
                "switch",
                str(staging_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            assert proc.stdout is not None
            out = (await proc.stdout.read()).decode("utf-8", errors="replace")
            code = await proc.wait()

            if code != 0 or "rolled-back" in out:
                reason = out.strip()[-300:] or "supervisor switch 失败"
                self._emit("rolled_back", reason)
                raise AppError("download_failed", f"升级失败已回滚: {reason}", status=500)
            self._emit("done")
            return {"version": release.version, "phase": "done"}
        except AppError as exc:
            shutil.rmtree(staging_root, ignore_errors=True)
            if "rolled_back" not in str(exc.message):
                self._emit("rolled_back", exc.message)
            raise

    def _emit(self, phase: str, reason: str | None = None) -> None:
        payload: dict[str, Any] = {"phase": phase}
        if reason:
            payload["reason"] = reason
        self._events.publish(TOPIC_PANEL, payload)


def _extract(archive: Path, dest: Path) -> None:
    dctx = zstandard.ZstdDecompressor()
    with (
        archive.open("rb") as fr,
        dctx.stream_reader(fr) as zr,
        tarfile.open(fileobj=zr, mode="r|") as tar,
    ):
        try:
            tar.extractall(dest, filter="data")  # noqa: S202
        except TypeError:
            tar.extractall(dest)
    # 兼容带单层根目录的包
    children = [c for c in dest.iterdir() if c.is_dir()]
    if len(children) == 1 and (children[0] / "backend").is_dir():
        src = children[0]
        for item in list(src.iterdir()):
            shutil.move(str(item), str(dest / item.name))
        src.rmdir()


def _emit_progress(events: EventBus, task: str) -> Any:
    async def cb(d: dict[str, Any]) -> None:
        events.publish("downloads", {"task": task, **d})

    return cb
