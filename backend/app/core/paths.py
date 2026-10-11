"""路径常量、目录布局与白名单校验。

架构不变量（docs/ARCHITECTURE.md 第 5 节 #1/#7）：
- 一切可重建之外的数据只写数据盘（LAUNCHPAD_DATA_DIR，默认 /root/autodl-tmp/launchpad-data）；
- 任何面向文件系统的用户输入必须经 safe_resolve 校验，拒绝越界与符号链接逃逸。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


class PathOutsideWhitelist(ValueError):
    """路径越出白名单根目录。"""


def _default_data_dir() -> Path:
    env = os.environ.get("LAUNCHPAD_DATA_DIR")
    if env:
        return Path(env).expanduser()
    if os.name == "posix":
        return Path("/root/autodl-tmp/launchpad-data")
    # Windows 开发环境回退，目标环境恒为 POSIX 分支
    return Path.home() / "launchpad-data"


def _default_launchpad_dir() -> Path:
    env = os.environ.get("LAUNCHPAD_DIR")
    if env:
        return Path(env).expanduser()
    if os.name == "posix":
        return Path("/root/launchpad")
    return Path.home() / "launchpad-dev"


@dataclass(frozen=True)
class Layout:
    """面板全部落盘路径的唯一权威定义。"""

    data_dir: Path
    launchpad_dir: Path
    versions_dir: Path = field(init=False)
    staging_dir: Path = field(init=False)
    shared_dir: Path = field(init=False)
    shared_models: Path = field(init=False)
    shared_output: Path = field(init=False)
    shared_input: Path = field(init=False)
    shared_user: Path = field(init=False)
    shared_workflows: Path = field(init=False)
    workflow_history: Path = field(init=False)
    state_dir: Path = field(init=False)
    logs_dir: Path = field(init=False)
    panel_releases_dir: Path = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "versions_dir", self.data_dir / "versions")
        object.__setattr__(self, "staging_dir", self.versions_dir / ".staging")
        object.__setattr__(self, "shared_dir", self.data_dir / "shared")
        object.__setattr__(self, "shared_models", self.shared_dir / "models")
        object.__setattr__(self, "shared_output", self.shared_dir / "output")
        object.__setattr__(self, "shared_input", self.shared_dir / "input")
        object.__setattr__(self, "shared_user", self.shared_dir / "user")
        object.__setattr__(self, "shared_workflows", self.shared_dir / "workflows")
        object.__setattr__(self, "workflow_history", self.shared_workflows / ".history")
        object.__setattr__(self, "state_dir", self.data_dir / "state")
        object.__setattr__(self, "logs_dir", self.data_dir / "logs")
        object.__setattr__(self, "panel_releases_dir", self.data_dir / "panel-releases")

    @property
    def shared_model_categories(self) -> list[Path]:
        return [self.shared_models / name for name in MODEL_CATEGORIES]

    def ensure(self) -> None:
        """建立全部白名单目录（幂等）。"""
        dirs = [
            self.versions_dir,
            self.staging_dir,
            self.shared_dir,
            self.shared_output,
            self.shared_input,
            self.shared_user,
            self.shared_workflows,
            self.workflow_history,
            self.state_dir,
            self.logs_dir,
            self.panel_releases_dir,
        ]
        dirs.extend(self.shared_model_categories)
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

    def current_link(self) -> Path:
        """ComfyUI 版本 current 符号链接路径。"""
        return self.versions_dir / "current"


MODEL_CATEGORIES = [
    "checkpoints",
    "diffusion_models",
    "controlnet",
    "loras",
    "text_encoders",
    "vae",
    "clip",
    "upscale_models",
    "embeddings",
]


def build_layout(
    data_dir: str | None = None, launchpad_dir: str | None = None
) -> Layout:
    return Layout(
        data_dir=Path(data_dir).expanduser() if data_dir else _default_data_dir(),
        launchpad_dir=(
            Path(launchpad_dir).expanduser() if launchpad_dir else _default_launchpad_dir()
        ),
    )


LAYOUT: Layout = build_layout()


def safe_resolve(base: Path, relative: str | Path) -> Path:
    """把 relative 解析进 base 之内，拒绝一切越界。

    拒绝：`..` 上跳、指向白名单外的绝对路径、经由符号链接逃逸出 base。
    返回 realpath 解析后的绝对路径。
    """
    base_real = Path(os.path.realpath(base))
    candidate = Path(relative)
    if candidate.is_absolute():
        resolved = Path(os.path.realpath(candidate))
    else:
        resolved = Path(os.path.realpath(base / candidate))
    if resolved != base_real and not resolved.is_relative_to(base_real):
        raise PathOutsideWhitelist(f"路径越出白名单 {base_real}: {relative}")
    return resolved
