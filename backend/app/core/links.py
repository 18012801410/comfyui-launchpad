"""目录链接工具：Linux symlink / Windows junction 的统一封装。

版本共享布局（FR-007）依赖目录链接；Windows 开发环境无 symlink 权限时退级 junction。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _points_to_target(link: Path, target: Path) -> bool:
    try:
        return Path(os.path.realpath(link)) == Path(os.path.realpath(target))
    except OSError:
        return False


def is_link(link: Path) -> bool:
    """是否为 symlink 或 Windows junction。"""
    if link.is_symlink():
        return True
    if sys.platform == "win32" and link.exists():
        try:
            return os.path.realpath(link) != str(link)
        except OSError:
            return False
    return False


def ensure_dir_link(target: Path, link: Path) -> None:
    """让 link 指向 target（目录）；已正确指向则幂等返回。"""
    if is_link(link):
        if _points_to_target(link, target):
            return
        remove_dir_link(link)
    link.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        try:
            os.symlink(target, link, target_is_directory=True)
        except OSError:
            # 无符号链接权限 → junction（cmd 内建命令，参数数组非 shell 拼接）
            subprocess.run(  # noqa: S603
                ["cmd", "/c", "mklink", "/J", str(link), str(target)],
                check=True,
                capture_output=True,
            )
    else:
        os.symlink(target, link, target_is_directory=True)


def remove_dir_link(link: Path) -> None:
    if not is_link(link):
        return
    if sys.platform == "win32" and not link.is_symlink():
        # junction 须用 rmdir 删除 reparse point 本身
        subprocess.run(  # noqa: S603
            ["cmd", "/c", "rmdir", str(link)], check=True, capture_output=True
        )
    else:
        link.unlink()
