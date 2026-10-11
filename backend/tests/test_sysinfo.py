"""sysinfo 采集器测试：样例文本驱动解析器 + TTL 缓存 + 单源失败隔离。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.paths import build_layout
from app.domain import sysinfo as sysinfo_mod
from app.domain.sysinfo import (
    SysinfoCollector,
    collect_gpu,
    parse_cgroup_v2,
    parse_cuda_version,
    parse_meminfo,
    parse_nvidia_smi_csv,
)

NVIDIA_CSV = """
NVIDIA GeForce RTX 4090, 550.127.08, 24564, 16688
"""

NVIDIA_CSV_MULTI = """
NVIDIA GeForce RTX 4090, 550.127.08, 24564, 16688
NVIDIA GeForce RTX 4090, 550.127.08, 24564, 8100
"""

NVIDIA_SMI_FULL = """
+-----------------------------------------------------------------------------------------+
| NVIDIA-SMI 550.127.08     Driver Version: 550.127.08     CUDA Version: 12.4             |
+-----------------------------------------------------------------------------------------+
"""

MEMINFO = """
MemTotal:       791141220 kB
MemFree:        123456789 kB
MemAvailable:   654321098 kB
Buffers:          123456 kB
"""

CGROUP_MAX = "2147483648\n"
CGROUP_CUR = "851443712\n"


def test_parse_nvidia_smi_single_gpu() -> None:
    info = parse_nvidia_smi_csv(NVIDIA_CSV)
    assert info.available is True
    assert info.count == 1
    assert "4090" in (info.name or "")
    assert info.driver == "550.127.08"
    assert info.vram_total_mb == 24564
    assert info.vram_used_mb == 16688


def test_parse_nvidia_smi_multi_gpu_counts() -> None:
    info = parse_nvidia_smi_csv(NVIDIA_CSV_MULTI)
    assert info.count == 2


def test_parse_nvidia_smi_bad_output() -> None:
    info = parse_nvidia_smi_csv("")
    assert info.available is False
    assert info.error


def test_parse_cuda_version() -> None:
    assert parse_cuda_version(NVIDIA_SMI_FULL) == "12.4"
    assert parse_cuda_version("nothing here") is None


def test_parse_meminfo() -> None:
    host_total, used = parse_meminfo(MEMINFO)
    assert host_total == 772599  # 791141220 kB / 1024 ≈ 772599 MB
    assert used == host_total - 638985  # MemAvailable 654321098 kB ≈ 638985 MB


def test_parse_cgroup_v2() -> None:
    limit, used = parse_cgroup_v2(CGROUP_MAX, CGROUP_CUR)
    assert limit == 2048  # 2 GB cgroup 限额
    assert used == 812
    limit2, _ = parse_cgroup_v2("max\n", CGROUP_CUR)
    assert limit2 is None


def test_collect_gpu_unavailable_when_no_nvidia_smi(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(args: list[str], timeout_s: float = 10.0, check: bool = True):  # type: ignore[no-untyped-def]
        raise FileNotFoundError("nvidia-smi")

    monkeypatch.setattr(sysinfo_mod, "run_cmd", boom)
    gpu, cuda = collect_gpu()
    assert gpu.available is False
    assert gpu.error
    assert cuda.available is False


def test_collector_ttl_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    layout = build_layout(data_dir=str(tmp_path))
    calls = {"n": 0}

    def fake_gpu() -> tuple:  # type: ignore[type-arg]
        calls["n"] += 1
        from app.domain.sysinfo import CudaInfo, GpuInfo

        return GpuInfo(name="FakeGPU", count=1, available=True), CudaInfo(available=True)

    monkeypatch.setattr(sysinfo_mod, "collect_gpu", fake_gpu)
    collector = SysinfoCollector(layout)
    s1 = collector.snapshot()
    s2 = collector.snapshot()
    assert calls["n"] == 1, "TTL 内二次快照不应重新执行采集"
    assert s1.gpu.name == "FakeGPU"
    assert s2.gpu.name == "FakeGPU"


def test_single_source_failure_isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    layout = build_layout(data_dir=str(tmp_path))

    def boom_gpu() -> tuple:  # type: ignore[type-arg]
        raise RuntimeError("nvidia-smi exploded")

    monkeypatch.setattr(sysinfo_mod, "collect_gpu", boom_gpu)
    collector = SysinfoCollector(layout)
    status = collector.snapshot()
    # GPU 源失败……
    assert status.gpu.available is False
    # ……其余源正常返回
    assert status.python_version
    assert status.disk.sys_total_gb is not None
