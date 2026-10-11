"""系统状态采集器：GPU / 内存 / 磁盘 / CUDA / Python 快照（API-008 数据源）。

设计约束（FR-005）：
- 单源失败隔离：任一采集器抛异常，其余字段正常返回，失败源 available=false + error；
- 结果 TTL 缓存，轮询不打爆底层命令；
- 解析器为纯函数（样例文本驱动测试），IO 与解析分离。
"""

from __future__ import annotations

import ctypes
import platform
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.paths import Layout
from app.infra.shell import run_cmd

CACHE_TTL_S = 2.0


@dataclass
class GpuInfo:
    name: str | None = None
    count: int = 0
    driver: str | None = None
    vram_total_mb: int | None = None
    vram_used_mb: int | None = None
    available: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class MemoryInfo:
    limit_mb: int | None = None
    used_mb: int | None = None
    host_total_mb: int | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        return d


@dataclass
class DiskInfo:
    sys_total_gb: float | None = None
    sys_free_gb: float | None = None
    data_total_gb: float | None = None
    data_free_gb: float | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class CudaInfo:
    available: bool = False
    version: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class SysStatus:
    gpu: GpuInfo = field(default_factory=GpuInfo)
    memory: MemoryInfo = field(default_factory=MemoryInfo)
    disk: DiskInfo = field(default_factory=DiskInfo)
    cuda: CudaInfo = field(default_factory=CudaInfo)
    python_version: str = ""
    comfy_process: str = "stopped"

    def to_dict(self) -> dict[str, Any]:
        return {
            "gpu": self.gpu.to_dict(),
            "memory": self.memory.to_dict(),
            "disk": self.disk.to_dict(),
            "cuda": self.cuda.to_dict(),
            "python_version": self.python_version,
            "comfy_process": self.comfy_process,
        }


# ---------- 纯解析函数（样例驱动测试） ----------

def parse_nvidia_smi_csv(output: str) -> GpuInfo:
    """解析 --query-gpu=… --format=csv,noheader,nounits 的输出。"""
    info = GpuInfo()
    lines = [ln.strip() for ln in output.strip().splitlines() if ln.strip()]
    if not lines:
        info.error = "nvidia-smi 无输出"
        return info
    info.count = len(lines)
    first = [c.strip() for c in lines[0].split(",")]
    if len(first) >= 4:
        info.name = first[0]
        info.driver = first[1]
        info.vram_total_mb = _to_int_mb(first[2])
        info.vram_used_mb = _to_int_mb(first[3])
        info.available = True
    else:
        info.error = f"nvidia-smi 输出格式异常: {lines[0][:100]}"
    return info


def _to_int_mb(raw: str) -> int | None:
    try:
        return int(round(float(raw.replace("MiB", "").replace("MB", "").strip())))
    except ValueError:
        return None


def parse_cuda_version(nvidia_smi_full_output: str) -> str | None:
    m = re.search(r"CUDA Version:\s*([0-9.]+)", nvidia_smi_full_output)
    return m.group(1) if m else None


def parse_meminfo(proc_meminfo_text: str) -> tuple[int, int]:
    """返回 (host_total_mb, available_mb)。"""
    total = avail = None
    for line in proc_meminfo_text.splitlines():
        if line.startswith("MemTotal:"):
            total = _parse_meminfo_kb(line)
        elif line.startswith("MemAvailable:"):
            avail = _parse_meminfo_kb(line)
        if total is not None and avail is not None:
            break
    if total is None:
        raise ValueError("MemTotal 缺失")
    avail = avail or 0
    return total, max(total - avail, 0)


def _parse_meminfo_kb(line: str) -> int:
    parts = line.split()
    kb = int(parts[1])
    return int(round(kb / 1024))


def parse_cgroup_v2(max_text: str, current_text: str) -> tuple[int | None, int]:
    """返回 (limit_mb, used_mb)；limit 为 "max" 时 None。"""
    limit: int | None = None
    stripped = max_text.strip()
    if stripped != "max":
        limit = int(round(int(stripped) / (1024 * 1024)))
    used = int(round(int(current_text.strip()) / (1024 * 1024)))
    return limit, used


# ---------- IO 采集器 ----------

def collect_gpu() -> tuple[GpuInfo, CudaInfo]:
    """采集 GPU 与 CUDA 信息；失败时 available=false + error（单源隔离）。"""
    try:
        res = run_cmd(
            [
                "nvidia-smi",
                "--query-gpu=name,driver_version,memory.total,memory.used",
                "--format=csv,noheader,nounits",
            ],
            timeout_s=5.0,
        )
        info = parse_nvidia_smi_csv(res.stdout)
        if not info.available:
            return info, CudaInfo(error=info.error)
        full = run_cmd(["nvidia-smi"], timeout_s=5.0)
        cuda = CudaInfo(available=True, version=parse_cuda_version(full.stdout))
        return info, cuda
    except Exception as exc:  # noqa: BLE001 - 单源失败隔离
        return GpuInfo(error=str(exc)[:200]), CudaInfo(error=str(exc)[:200])


def collect_memory() -> MemoryInfo:
    if Path("/proc/meminfo").exists():
        text = Path("/proc/meminfo").read_text(encoding="utf-8")
        host_total, used = parse_meminfo(text)
        limit: int | None = host_total
        cgroup_max = Path("/sys/fs/cgroup/memory.max")
        cgroup_cur = Path("/sys/fs/cgroup/memory.current")
        if cgroup_max.exists() and cgroup_cur.exists():
            limit, cgroup_used = parse_cgroup_v2(
                cgroup_max.read_text(encoding="utf-8"),
                cgroup_cur.read_text(encoding="utf-8"),
            )
            used = max(used, cgroup_used)
        return MemoryInfo(limit_mb=limit, used_mb=used, host_total_mb=host_total)
    # Windows 开发环境
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if getattr(ctypes, "windll", None) is not None and ctypes.windll.kernel32.GlobalMemoryStatusEx(
        ctypes.byref(stat)
    ):
        total_mb = int(stat.ullTotalPhys // (1024 * 1024))
        avail_mb = int(stat.ullAvailPhys // (1024 * 1024))
        return MemoryInfo(
            limit_mb=total_mb, used_mb=max(total_mb - avail_mb, 0), host_total_mb=total_mb
        )
    return MemoryInfo(error="无法读取内存信息")


def collect_disk(layout: Layout) -> DiskInfo:
    sys_usage = shutil.disk_usage(Path.home())
    data_path = layout.data_dir
    if not data_path.exists():
        data_path = Path.home()
    data_usage = shutil.disk_usage(data_path)
    return DiskInfo(
        sys_total_gb=round(sys_usage.total / 1024**3, 1),
        sys_free_gb=round(sys_usage.free / 1024**3, 1),
        data_total_gb=round(data_usage.total / 1024**3, 1),
        data_free_gb=round(data_usage.free / 1024**3, 1),
    )


class SysinfoCollector:
    """带 TTL 缓存的快照采集入口。"""

    def __init__(self, layout: Layout) -> None:
        self._layout = layout
        self._cache: SysStatus | None = None
        self._cached_at = 0.0

    def snapshot(self, comfy_process_state: str = "stopped") -> SysStatus:
        now = time.monotonic()
        if self._cache is not None and now - self._cached_at < CACHE_TTL_S:
            cached = self._cache
            cached.comfy_process = comfy_process_state
            return cached

        status = SysStatus(python_version=platform.python_version())
        status.comfy_process = comfy_process_state

        try:
            status.gpu, status.cuda = collect_gpu()
        except Exception as exc:  # noqa: BLE001
            status.gpu = GpuInfo(error=str(exc)[:200])

        try:
            status.memory = collect_memory()
        except Exception as exc:  # noqa: BLE001
            status.memory = MemoryInfo(error=str(exc)[:200])

        try:
            status.disk = collect_disk(self._layout)
        except Exception as exc:  # noqa: BLE001
            status.disk = DiskInfo(error=str(exc)[:200])

        self._cache = status
        self._cached_at = now
        return status
