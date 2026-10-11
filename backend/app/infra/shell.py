"""跨平台子进程封装：参数数组、无 shell、超时保护。

安全不变量（AI_RULES）：禁止 shell=True 拼接命令。
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass


class ShellCommandError(RuntimeError):
    def __init__(self, message: str, returncode: int | None = None) -> None:
        super().__init__(message)
        self.returncode = returncode


@dataclass
class ShellResult:
    stdout: str
    returncode: int


def run_cmd(
    args: list[str], timeout_s: float = 10.0, check: bool = True
) -> ShellResult:
    """执行外部命令；绝不使用 shell。"""
    try:
        proc = subprocess.run(  # noqa: S603 - 参数数组形式，无 shell
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ShellCommandError(f"命令不存在: {args[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ShellCommandError(f"命令超时: {' '.join(args)}") from exc
    if check and proc.returncode != 0:
        raise ShellCommandError(
            f"命令失败({proc.returncode}): {' '.join(args)}\n{proc.stderr[:500]}",
            returncode=proc.returncode,
        )
    return ShellResult(stdout=proc.stdout, returncode=proc.returncode)
