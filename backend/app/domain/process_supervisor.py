"""ComfyUI 进程监督器：ProcessState 状态机 + 子进程组管理 + 日志采集 + 对账。

领域核心（docs/DOMAIN_MODEL.md「ComfyProcess」）：
- 五态状态机，迁移合法性在本模块内强制，外部只能发命令；
- 单一权威状态（架构不变量 #3）：面板重启后经 reconcile() 对账；
- 纯领域层：不 import fastapi/httpx；就绪探测用 TCP 连接（socket 标准库）。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import socket
import sys
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from app.core.errors import AppError, InvalidTransition
from app.core.events import EventBus
from app.core.paths import Layout

READINESS_INTERVAL_S = 1.0
READINESS_TIMEOUT_S = 300.0
STOP_TIMEOUT_S = 10.0
RING_BUFFER_SIZE = 2000

_TOPIC_PROCESS = "process"
_TOPIC_LOGS = "logs"


class ProcessState(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    FAILED = "failed"


_ALLOWED_TRANSITIONS: dict[ProcessState, set[ProcessState]] = {
    ProcessState.STOPPED: {ProcessState.STARTING},
    ProcessState.STARTING: {
        ProcessState.RUNNING,
        ProcessState.FAILED,
        ProcessState.STOPPING,
    },
    ProcessState.RUNNING: {ProcessState.STOPPING, ProcessState.FAILED},
    ProcessState.STOPPING: {ProcessState.STOPPED},
    # failed → starting 允许失败后直接重启（清位隐含在 start 守卫中）
    ProcessState.FAILED: {ProcessState.STOPPED, ProcessState.STARTING},
}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def process_alive(pid: int) -> bool:
    """跨平台进程存活检查（绝不向目标进程发送终止信号）。"""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32  # noqa: PLC0415
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def tcp_probe(port: int, host: str = "127.0.0.1", timeout: float = 1.0) -> bool:
    """端口就绪探测（阻塞，建议经 asyncio.to_thread 调用）。"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@dataclass
class ProcessSnapshot:
    """API-004 /api/comfy/status 的领域来源。"""

    state: ProcessState
    pid: int | None = None
    started_at: str | None = None
    stopped_at: str | None = None
    exit_code: int | None = None
    version: str | None = None
    port: int | None = None
    port_ready: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "pid": self.pid,
            "started_at": self.started_at,
            "stopped_at": self.stopped_at,
            "exit_code": self.exit_code,
            "version": self.version,
            "port": self.port,
            "port_ready": self.port_ready,
        }


class ProcessSupervisor:
    """ComfyUI 子进程的唯一管理者。"""

    def __init__(
        self,
        layout: Layout,
        events: EventBus | None = None,
        readiness_timeout_s: float = READINESS_TIMEOUT_S,
        stop_timeout_s: float = STOP_TIMEOUT_S,
    ) -> None:
        self._layout = layout
        self._events = events or EventBus()
        self._readiness_timeout = readiness_timeout_s
        self._stop_timeout = stop_timeout_s

        self._state = ProcessState.STOPPED
        self._proc: asyncio.subprocess.Process | None = None
        self._pid: int | None = None
        self._started_at: str | None = None
        self._stopped_at: str | None = None
        self._exit_code: int | None = None
        self._port: int | None = None
        self._version: str | None = None
        self._launch_snapshot: dict[str, Any] | None = None

        self._ring: deque[dict[str, str]] = deque(maxlen=RING_BUFFER_SIZE)
        self._cursor = 0
        self._reader_task: asyncio.Task[None] | None = None
        self._monitor_task: asyncio.Task[None] | None = None
        self._stop_lock = asyncio.Lock()
        self._pidfile = layout.state_dir / "comfy-process.json"

    # ---------- 状态机 ----------

    @property
    def state(self) -> ProcessState:
        return self._state

    def _set_state(self, target: ProcessState) -> None:
        if target not in _ALLOWED_TRANSITIONS[self._state]:
            raise InvalidTransition(self._state.value, target.value)
        self._state = target
        self._events.publish(
            _TOPIC_PROCESS, {"state": target.value, "pid": self._pid}
        )

    # ---------- 日志 ----------

    def _append_log(self, line: str, source: str = "comfy") -> None:
        self._cursor += 1
        entry = {"cursor": str(self._cursor), "ts": _utcnow_iso(), "source": source, "line": line}
        self._ring.append(entry)
        self._events.publish(_TOPIC_LOGS, {"source": source, "line": line})

    def recent_logs(self, tail: int = 300) -> list[dict[str, str]]:
        entries = list(self._ring)
        return entries[-tail:]

    # ---------- 命令 ----------

    async def start(
        self,
        cmd: list[str],
        workdir: Path,
        version: str | None,
        env: dict[str, str] | None = None,
    ) -> ProcessSnapshot:
        """启动 ComfyUI。

        cmd 为完整命令（[python, "main.py", ...args]，由调用方依 LaunchConfig 拼装）；
        workdir 为当前版本目录（含 main.py，即「已安装版本」的领域校验点）。
        """
        if self._state in (ProcessState.STARTING, ProcessState.RUNNING):
            raise AppError(
                "conflict_process_running", "ComfyUI 已在运行或启动中", status=409
            )
        # stopping 期间禁止 spawn：等旧进程完全退出（否则 pid 文件互相覆盖、端口竞争）
        wait_deadline = time.monotonic() + self._stop_timeout + 5
        while self._state == ProcessState.STOPPING:
            if time.monotonic() > wait_deadline:
                raise AppError("internal", "上一停止流程超时未完成", status=500)
            await asyncio.sleep(0.05)
        if self._state in (ProcessState.STARTING, ProcessState.RUNNING):
            raise AppError(
                "conflict_process_running", "ComfyUI 已在运行或启动中", status=409
            )
        if not workdir.is_dir() or not (workdir / "main.py").is_file():
            raise AppError(
                "version_not_installed", "尚未安装任何 ComfyUI 版本（current 无效）", status=404
            )

        self._set_state(ProcessState.STARTING)
        self._exit_code = None
        self._stopped_at = None
        self._version = version
        self._launch_snapshot = {"args": cmd, "workdir": str(workdir)}

        child_env = os.environ.copy()
        if env:
            child_env.update(env)

        kwargs: dict[str, Any] = {}
        if sys.platform != "win32":
            kwargs["start_new_session"] = True  # 独立进程组，便于 killpg

        try:
            self._proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(workdir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=child_env,
                **kwargs,
            )
        except OSError as exc:
            self._set_state(ProcessState.FAILED)
            self._append_log(f"启动失败: {exc}")
            raise AppError("internal", f"启动 ComfyUI 失败: {exc}", status=500) from exc

        self._pid = self._proc.pid
        self._started_at = _utcnow_iso()
        self._port = self._extract_port(cmd)
        self._write_pidfile()

        self._append_log(f"ComfyUI 启动中 (pid={self._pid}, port={self._port})")
        self._reader_task = asyncio.create_task(self._read_output())
        self._monitor_task = asyncio.create_task(self._monitor_exit())

        ready = await self._wait_ready(self._port or 8188)
        if ready:
            self._set_state(ProcessState.RUNNING)
            self._append_log("ComfyUI 就绪")
        elif self._state == ProcessState.STARTING:
            # 探测超时但进程仍在：保持 starting，交由 monitor 依据退出码流转
            self._append_log("就绪探测超时，进程仍在运行，继续等待…")
        return self.snapshot()

    async def stop(self, timeout: float | None = None) -> ProcessSnapshot:
        """停止进程；对 stopped/failed 幂等成功；并发调用合并为一次停止。"""
        if self._state in (ProcessState.STOPPED, ProcessState.FAILED):
            if self._state == ProcessState.FAILED:
                self._set_state(ProcessState.STOPPED)
            return self.snapshot()
        if self._state == ProcessState.STOPPING:
            # 已有停止流程在跑：等它结束
            while self._state == ProcessState.STOPPING:
                await asyncio.sleep(0.05)
            return self.snapshot()
        async with self._stop_lock:
            if self._state == ProcessState.STOPPING:
                while self._state == ProcessState.STOPPING:
                    await asyncio.sleep(0.05)
                return self.snapshot()
            if self._state in (ProcessState.STOPPED,):
                return self.snapshot()
            self._set_state(ProcessState.STOPPING)
            timeout = timeout if timeout is not None else self._stop_timeout
            proc = self._proc
            if proc is not None:
                await self._terminate(proc)
                try:
                    await asyncio.wait_for(proc.wait(), timeout=timeout)
                except asyncio.TimeoutError:
                    await self._kill(proc)
                    await proc.wait()
            await self._finalize(stopped_by_user=True, exit_code=proc.returncode if proc else None)
            return self.snapshot()

    async def restart(
        self,
        cmd: list[str],
        workdir: Path,
        version: str | None,
        env: dict[str, str] | None = None,
    ) -> ProcessSnapshot:
        if self._state in (ProcessState.RUNNING, ProcessState.STARTING):
            await self.stop()
        return await self.start(
            cmd=cmd,
            workdir=workdir,
            version=version,
            env=env,
        )

    # ---------- 对账 ----------

    def reconcile(self) -> ProcessSnapshot:
        """面板重启后调用：依据 pid 文件对账遗留进程。"""
        raw = self._read_pidfile()
        if raw is None:
            if self._state == ProcessState.STOPPED:
                return self.snapshot()
            # 无 pid 文件但内存态非 stopped（异常路径）—— 回落 stopped
            self._state = ProcessState.STOPPED
            return self.snapshot()

        pid = int(raw.get("pid", 0))
        alive = process_alive(pid)
        if alive:
            # 遗留进程仍存活：纳入管理（日志管道无法恢复，重启后才有新日志）
            self._pid = pid
            self._started_at = raw.get("started_at")
            self._port = raw.get("port")
            self._version = raw.get("version")
            self._append_log(f"对账：发现遗留 ComfyUI 进程 pid={pid}，纳入管理")
            self._state = ProcessState.RUNNING
            self._events.publish(_TOPIC_PROCESS, {"state": "running", "pid": pid})
        else:
            self._clear_pidfile()
            self._append_log(f"对账：pid={pid} 已不存在，状态回 stopped")
            self._state = ProcessState.STOPPED
        return self.snapshot()

    # ---------- 快照 ----------

    def snapshot(self) -> ProcessSnapshot:
        return ProcessSnapshot(
            state=self._state,
            pid=self._pid,
            started_at=self._started_at,
            stopped_at=self._stopped_at,
            exit_code=self._exit_code,
            version=self._version,
            port=self._port,
            port_ready=self._state == ProcessState.RUNNING,
        )

    # ---------- 内部 ----------

    @staticmethod
    def _extract_port(cli_args: list[str]) -> int:
        if "--port" in cli_args:
            idx = cli_args.index("--port")
            if idx + 1 < len(cli_args):
                try:
                    return int(cli_args[idx + 1])
                except ValueError:
                    pass
        return 8188

    def _write_pidfile(self) -> None:
        self._pidfile.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "pid": self._pid,
            "started_at": self._started_at,
            "port": self._port,
            "version": self._version,
        }
        self._pidfile.write_text(json.dumps(data), encoding="utf-8")

    def _read_pidfile(self) -> dict[str, Any] | None:
        try:
            raw = json.loads(self._pidfile.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) and raw.get("pid") else None
        except (OSError, json.JSONDecodeError):
            return None

    def _clear_pidfile(self) -> None:
        with contextlib.suppress(OSError):
            self._pidfile.unlink()

    async def _read_output(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").rstrip("\r\n")
            if text:
                self._append_log(text)

    async def _monitor_exit(self) -> None:
        proc = self._proc
        if proc is None:
            return
        code = await proc.wait()
        self._exit_code = code
        if self._state == ProcessState.STOPPING:
            return  # stop() 负责收尾
        # 非用户停止的退出 → failed
        self._append_log(f"ComfyUI 进程异常退出，exit_code={code}")
        self._state = ProcessState.FAILED
        self._events.publish(
            _TOPIC_PROCESS, {"state": "failed", "pid": self._pid, "exit_code": code}
        )
        self._clear_pidfile()

    async def _wait_ready(self, port: int) -> bool:
        deadline = time.monotonic() + self._readiness_timeout
        while time.monotonic() < deadline:
            if self._proc is not None and self._proc.returncode is not None:
                return False
            if self._state == ProcessState.STOPPING:
                return False
            if await asyncio.to_thread(tcp_probe, port):
                return True
            await asyncio.sleep(READINESS_INTERVAL_S)
        return False

    async def _terminate(self, proc: asyncio.subprocess.Process) -> None:
        if sys.platform == "win32":
            proc.terminate()
        else:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                proc.terminate()

    async def _kill(self, proc: asyncio.subprocess.Process) -> None:
        self._append_log("优雅终止超时，升级 SIGKILL")
        if sys.platform == "win32":
            proc.kill()
        else:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()

    async def _finalize(self, stopped_by_user: bool, exit_code: int | None) -> None:
        self._exit_code = exit_code
        self._stopped_at = _utcnow_iso()
        self._proc = None
        self._pid = None
        self._clear_pidfile()
        for task in (self._reader_task, self._monitor_task):
            if task and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        self._reader_task = None
        self._monitor_task = None
        self._set_state(ProcessState.STOPPED)
