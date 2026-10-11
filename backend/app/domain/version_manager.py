"""版本管理器：当前版本定位与版本内 Python 解释器解析。

TASK-008 将扩展：索引拉取/安装/切换/删除。本文件保持领域纯净（无 fastapi/httpx，
网络访问经 infra.downloader，由 API 层编排）。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from app.core.paths import Layout


def resolve_current(layout: Layout) -> tuple[Path, str] | None:
    """解析 current 符号链接 → (版本目录, 版本号)；无效返回 None。

    不变量（DOMAIN_MODEL）：current 当且仅当指向一个含 main.py 的 ready 实例。
    """
    link = layout.current_link()
    if not link.exists():
        return None
    target = Path(link.resolve())
    if not target.is_dir() or not (target / "main.py").is_file():
        return None
    version = _version_from_name(target.name)
    return target, version


def python_exe_for(version_dir: Path) -> Path:
    """版本内独立 venv 的解释器；缺失回退面板自身解释器。"""
    sub = "Scripts" if sys.platform == "win32" else "bin"
    exe = "python.exe" if sys.platform == "win32" else "python"
    candidate = version_dir / "venv" / sub / exe
    return candidate if candidate.is_file() else Path(sys.executable)


def _version_from_name(name: str) -> str:
    m = re.match(r"(\d+\.\d+\.\d+.*)", name)
    return m.group(1) if m else name
