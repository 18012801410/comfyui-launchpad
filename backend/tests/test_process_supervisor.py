"""进程监督器测试：状态机迁移、启动/停止、崩溃、日志、对账。

全部用 fake_comfy.py 驱动，不依赖真实 ComfyUI/GPU；结束后断言无孤儿进程。
"""

from __future__ import annotations

import asyncio
import socket
import sys
import time
from pathlib import Path

import pytest

from app.core.errors import AppError, InvalidTransition
from app.core.events import EventBus
from app.core.paths import Layout
from app.domain.process_supervisor import ProcessState, ProcessSupervisor, process_alive

HELPERS = Path(__file__).parent / "helpers"
FAKE_COMFY = HELPERS / "fake_comfy.py"
PY = sys.executable


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def fake_cmd(
    port: int, hold: float = 3.0, exit_code: int = 0, lines: int = 2
) -> list[str]:
    """完整子进程命令：python + fake 入口 + 参数（模拟调用方拼装）。"""
    return [
        PY,
        str(FAKE_COMFY),
        "--port",
        str(port),
        "--hold",
        str(hold),
        "--exit-code",
        str(exit_code),
        "--lines",
        str(lines),
    ]


async def _wait_state(
    sup: ProcessSupervisor, target: ProcessState, timeout: float = 8.0
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if sup.state == target:
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"等待状态 {target} 超时，当前 {sup.state}")


@pytest.fixture()
def workdir(tmp_path: Path) -> Path:
    """伪造一个已安装版本目录（含 main.py）。"""
    d = tmp_path / "versions" / "0.39.0"
    d.mkdir(parents=True)
    (d / "main.py").write_text("# fake comfy entry\n", encoding="utf-8")
    return d


@pytest.fixture()
def supervisor(layout: Layout) -> ProcessSupervisor:
    return ProcessSupervisor(layout, readiness_timeout_s=6.0, stop_timeout_s=5.0)


async def test_start_run_stop_happy_path(supervisor: ProcessSupervisor, workdir: Path) -> None:
    bus = EventBus()
    bus.subscribe({"process", "logs"})
    sub = bus.subscribers[0]
    supervisor._events = bus

    snap = await supervisor.start(fake_cmd(free_port()), workdir, "0.39.0")
    assert supervisor.state == ProcessState.RUNNING
    assert snap.pid and snap.port and snap.port > 0
    assert snap.started_at

    # 日志被采集
    logs = supervisor.recent_logs(tail=50)
    assert any("ready on" in e["line"] for e in logs)
    # 事件发布
    got_running = False
    while not sub.queue.empty():
        topic, payload = sub.queue.get_nowait()
        if topic == "process" and payload.get("state") == "running":
            got_running = True
    assert got_running

    stop_snap = await supervisor.stop()
    assert supervisor.state == ProcessState.STOPPED
    assert stop_snap.stopped_at
    assert supervisor._read_pidfile() is None


async def test_double_start_conflicts(supervisor: ProcessSupervisor, workdir: Path) -> None:
    await supervisor.start(fake_cmd(free_port(), hold=10), workdir, "0.39.0")
    with pytest.raises(AppError) as ei:
        await supervisor.start(fake_cmd(free_port()), workdir, "0.39.0")
    assert ei.value.code == "conflict_process_running"
    await supervisor.stop()


async def test_stop_idempotent_when_stopped(supervisor: ProcessSupervisor) -> None:
    snap = await supervisor.stop()
    assert snap.state == ProcessState.STOPPED


async def test_stop_concurrent_calls_merge(
    supervisor: ProcessSupervisor, workdir: Path
) -> None:
    await supervisor.start(fake_cmd(free_port(), hold=10), workdir, "0.39.0")
    results = await asyncio.gather(supervisor.stop(), supervisor.stop())
    assert supervisor.state == ProcessState.STOPPED
    assert all(r.state == ProcessState.STOPPED for r in results)


async def test_crash_becomes_failed(supervisor: ProcessSupervisor, workdir: Path) -> None:
    # hold=0 且 exit-code=3：进程立即退出
    await supervisor.start(fake_cmd(free_port(), hold=0, exit_code=3), workdir, "0.39.0")
    await _wait_state(supervisor, ProcessState.FAILED)
    assert supervisor.snapshot().exit_code == 3
    # failed → stopped（用户确认/清位）
    await supervisor.stop()
    assert supervisor.state == ProcessState.STOPPED


async def test_start_requires_installed_workdir(
    supervisor: ProcessSupervisor, tmp_path: Path
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(AppError) as ei:
        await supervisor.start(fake_cmd(free_port()), empty, "0.39.0")
    assert ei.value.code == "version_not_installed"


async def test_invalid_transition_rejected(supervisor: ProcessSupervisor) -> None:
    with pytest.raises(InvalidTransition):
        supervisor._set_state(ProcessState.RUNNING)  # stopped → running 非法
    supervisor._state = ProcessState.RUNNING
    with pytest.raises(InvalidTransition):
        supervisor._set_state(ProcessState.STARTING)  # running → starting 非法


async def test_reconcile_dead_pid_back_to_stopped(
    supervisor: ProcessSupervisor, layout: Layout
) -> None:
    layout.state_dir.mkdir(parents=True, exist_ok=True)
    pidfile = layout.state_dir / "comfy-process.json"
    pidfile.write_text('{"pid": 999999999, "port": 8188}', encoding="utf-8")
    snap = supervisor.reconcile()
    assert snap.state == ProcessState.STOPPED
    assert not pidfile.exists()


async def test_reconcile_adopts_live_pid(
    supervisor: ProcessSupervisor, layout: Layout
) -> None:
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-c", "import time; time.sleep(30)"
    )
    try:
        layout.state_dir.mkdir(parents=True, exist_ok=True)
        pidfile = layout.state_dir / "comfy-process.json"
        pidfile.write_text(
            f'{{"pid": {proc.pid}, "port": 8188, "version": "0.39.0"}}', encoding="utf-8"
        )
        snap = supervisor.reconcile()
        assert snap.state == ProcessState.RUNNING
        assert snap.pid == proc.pid
    finally:
        proc.terminate()
        await proc.wait()


async def test_no_orphan_after_stop(supervisor: ProcessSupervisor, workdir: Path) -> None:
    snap = await supervisor.start(fake_cmd(free_port(), hold=30), workdir, "0.39.0")
    pid = snap.pid
    assert pid is not None
    await supervisor.stop()
    await asyncio.sleep(0.2)
    assert not process_alive(pid), "停止后子进程仍存活（孤儿进程）"


async def test_start_during_stopping_waits(
    supervisor: ProcessSupervisor, workdir: Path
) -> None:
    """启动撞上停止进行中：必须等待旧进程完全退出后再 spawn，不得穿透。"""
    await supervisor.start(fake_cmd(free_port(), hold=10), workdir, "0.39.0")
    stop_task = asyncio.create_task(supervisor.stop())
    await asyncio.sleep(0.05)  # 让 stop 先进入 stopping 态
    snap = await supervisor.start(fake_cmd(free_port(), hold=5), workdir, "0.39.0")
    await stop_task
    assert supervisor.state == ProcessState.RUNNING
    assert snap.pid is not None
    await supervisor.stop()


async def test_restart_from_running(supervisor: ProcessSupervisor, workdir: Path) -> None:
    await supervisor.start(fake_cmd(free_port(), hold=30), workdir, "0.39.0")
    first_pid = supervisor.snapshot().pid
    await supervisor.restart(fake_cmd(free_port(), hold=30), workdir, "0.39.0")
    assert supervisor.state == ProcessState.RUNNING
    assert supervisor.snapshot().pid != first_pid
    await supervisor.stop()
