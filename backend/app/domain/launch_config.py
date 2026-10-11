"""启动配置（LaunchConfig）：ComfyUI 启动参数的领域模型与 CLI 拼装。

不变量（docs/DOMAIN_MODEL.md）：端口范围受限且不得与面板端口相同；
extra_args 经字符白名单校验（防注入，exec 无 shell 下的纵深防御）。
"""

from __future__ import annotations

import re
import shlex
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, field_validator

from app.core.config import read_json_with_backup, write_json_atomic
from app.core.errors import AppError

_EXTRA_ARGS_RE = re.compile(r"^[A-Za-z0-9\s._=/:\-]*$")
_EXTRA_ARGS_MAX_LEN = 500


class Preset(str, Enum):
    DEFAULT = "default"
    LOW_VRAM = "low_vram"
    FP16_FAST = "fp16_fast"
    CUSTOM = "custom"


# 预设 → ComfyUI 额外参数（保守选择，均为官方 main.py 支持的参数）
PRESET_ARGS: dict[Preset, list[str]] = {
    Preset.DEFAULT: [],
    Preset.LOW_VRAM: ["--lowvram"],
    Preset.FP16_FAST: ["--force-fp16"],
}


class LaunchConfig(BaseModel):
    listen_port: int = 8188
    preset: Preset = Preset.DEFAULT
    extra_args: str = ""
    academic_accel: bool = False

    @field_validator("listen_port")
    @classmethod
    def _port_range(cls, v: int) -> int:
        if not 1024 <= v <= 65535:
            raise ValueError("端口须在 1024-65535 之间")
        return v

    @field_validator("extra_args")
    @classmethod
    def _extra_args_whitelist(cls, v: str) -> str:
        if len(v) > _EXTRA_ARGS_MAX_LEN:
            raise AppError(
                "invalid_launch_args", f"额外参数超长（>{_EXTRA_ARGS_MAX_LEN}）"
            )
        if v and not _EXTRA_ARGS_RE.match(v):
            raise AppError(
                "invalid_launch_args", "额外参数含非法字符（仅允许字母数字与 ._=/:- 和空白）"
            )
        return v.strip()

    def build_cli_args(
        self, panel_port: int = 6006, python_exe: str | None = None
    ) -> list[str]:
        """拼装 ComfyUI 启动命令行（不含 python 可执行文件本身）。"""
        if self.listen_port == panel_port:
            raise AppError(
                "invalid_launch_args",
                f"ComfyUI 端口不得与面板端口相同（{panel_port}）",
            )
        args = ["--listen", "127.0.0.1", "--port", str(self.listen_port)]
        args.extend(PRESET_ARGS.get(self.preset, []))
        if self.extra_args:
            args.extend(shlex.split(self.extra_args, posix=False))
        return args


class LaunchConfigStore:
    """launch-config.json 的类型化读写（当前生效配置，单例）。"""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> LaunchConfig:
        if not self.path.exists():
            return LaunchConfig()
        raw = read_json_with_backup(self.path)
        if not raw:
            return LaunchConfig()
        return LaunchConfig.model_validate(raw)

    def save(self, config: LaunchConfig) -> None:
        write_json_atomic(self.path, config.model_dump(mode="json"))
