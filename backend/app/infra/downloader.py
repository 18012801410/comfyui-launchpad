"""统一下载器：进度回调、SHA-256 校验、原子落盘、学术加速装配与降级。

提供方边界（架构不变量 #6）：渠道 URL 与加速机制只在本模块与 core.config 出现。
原子性（不变量 #2）：先写 .part → 校验 → os.replace 成正式名；半成品不进正式路径。
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
import re
import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx

from app.core.errors import AppError

CHUNK_SIZE = 64 * 1024
FREE_SPACE_FACTOR = 1.2  # 预检：剩余空间须 ≥ 预期大小 × 1.2
NETWORK_TURBO_PATH = Path("/etc/network_turbo")

ProgressCB = Callable[[dict[str, Any]], Awaitable[None]]


class DownloadError(AppError):
    pass


def _err(code: str, message: str, status: int = 502) -> AppError:
    return AppError(code, message, status=status)


# ---------- 学术加速 ----------

_ACCEL_EXPORT_RE = re.compile(
    r"""^export\s+'?(https?_proxy|all_proxy|no_proxy)=(?:['"])?([^'"\s]+)""",
    re.MULTILINE,
)


def parse_network_turbo(text: str) -> dict[str, str]:
    """解析 /etc/network_turbo 的 export 行 → 代理环境变量。"""
    return {m.group(1): m.group(2) for m in _ACCEL_EXPORT_RE.finditer(text)}


def build_accel_env(enabled: bool) -> dict[str, str] | None:
    """启用加速时读取 AutoDL 学术加速脚本；不可用则返回 None（优雅降级直连）。"""
    if not enabled:
        return None
    try:
        if NETWORK_TURBO_PATH.exists():
            return parse_network_turbo(
                NETWORK_TURBO_PATH.read_text(encoding="utf-8", errors="replace")
            )
    except OSError:
        pass
    return None  # 降级：直连


def accel_httpx_proxy(accel_env: dict[str, str] | None) -> str | None:
    if not accel_env:
        return None
    return accel_env.get("https_proxy") or accel_env.get("http_proxy")


# ---------- 下载 ----------

async def _verify_free_space(dest_dir: Path, expected_bytes: int | None) -> None:
    if expected_bytes is None:
        return
    usage = await asyncio.to_thread(shutil.disk_usage, dest_dir)
    need = int(expected_bytes * FREE_SPACE_FACTOR)
    if usage.free < need:
        raise _err(
            "disk_insufficient",
            f"磁盘空间不足：需要约 {need // (1024 * 1024)} MB，"
            f"剩余 {usage.free // (1024 * 1024)} MB",
            status=507,
        )


async def download_file(
    url: str,
    dest_dir: Path,
    filename: str,
    expected_sha256: str | None = None,
    expected_size: int | None = None,
    accel_env: dict[str, str] | None = None,
    on_progress: ProgressCB | None = None,
    client: httpx.AsyncClient | None = None,
) -> Path:
    """下载到 dest_dir/filename（原子落盘 + SHA-256 校验 + 进度回调）。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    final_path = dest_dir / filename
    part_path = dest_dir / (filename + ".part")
    if part_path.exists():
        # 断点提示：MVP 不做续传，清理后重下（日志可见提示）
        part_path.unlink()

    await _verify_free_space(dest_dir, expected_size)

    proxy = accel_httpx_proxy(accel_env)
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(
            trust_env=False,
            proxy=proxy,
            timeout=httpx.Timeout(connect=15.0, read=60.0, write=60.0, pool=15.0),
            follow_redirects=True,
        )
    try:
        received = 0
        started = asyncio.get_event_loop().time()
        f = part_path.open("wb")
        try:
            async with client.stream("GET", url) as resp:
                if resp.status_code >= 400:
                    raise _err(
                        "download_failed",
                        f"下载失败 HTTP {resp.status_code}: {url}",
                    )
                total = int(resp.headers.get("content-length", 0)) or expected_size
                if expected_size is None:
                    await _verify_free_space(dest_dir, total)
                async for chunk in resp.aiter_bytes(chunk_size=CHUNK_SIZE):
                    f.write(chunk)
                    received += len(chunk)
                    if on_progress is not None:
                        elapsed = max(
                            asyncio.get_event_loop().time() - started, 0.001
                        )
                        await on_progress(
                            {
                                "received": received,
                                "total": total,
                                "speed_bps": int(received / elapsed),
                            }
                        )
        finally:
            # 先关闭句柄再清理（Windows 不允许删除打开中的文件）
            f.close()
        # 校验
        if expected_sha256 is not None:
            actual = await asyncio.to_thread(_sha256_of, part_path)
            if actual != expected_sha256.lower():
                _cleanup_part(part_path)
                raise _err(
                    "checksum_mismatch",
                    f"校验和不匹配：期望 {expected_sha256[:12]}…，实际 {actual[:12]}…",
                )
        os.replace(part_path, final_path)
        return final_path
    except httpx.HTTPError as exc:
        _cleanup_part(part_path)
        raise _err("download_failed", f"网络错误: {exc}") from exc
    except AppError:
        _cleanup_part(part_path)
        raise
    finally:
        if owns_client:
            await client.aclose()


def _cleanup_part(part_path: Path) -> None:
    with contextlib.suppress(OSError):
        part_path.unlink(missing_ok=True)


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            block = f.read(1024 * 1024)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


async def fetch_json(
    url: str,
    accel_env: dict[str, str] | None = None,
    timeout_s: float = 20.0,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """拉取 JSON 索引；失败抛 download_failed，由调用方决定是否降级用缓存。"""
    proxy = accel_httpx_proxy(accel_env)
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(
            trust_env=False, proxy=proxy, follow_redirects=True, timeout=timeout_s
        )
    try:
        resp = await client.get(url, headers={"Accept": "application/json"})
        if resp.status_code >= 400:
            raise _err("download_failed", f"索引拉取失败 HTTP {resp.status_code}: {url}")
        data = resp.json()
        if not isinstance(data, dict):
            raise _err("download_failed", f"索引格式异常（非 JSON 对象）: {url}")
        return data
    except httpx.HTTPError as exc:
        raise _err("download_failed", f"网络错误: {exc}") from exc
    finally:
        if owns_client:
            await client.aclose()
