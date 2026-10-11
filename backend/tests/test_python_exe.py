"""python_exe_for 的 venv/.venv 兼容测试（ComfyUI Desktop 用 .venv）。"""

from __future__ import annotations

import sys
from pathlib import Path

from app.domain.version_manager import python_exe_for


def _make_venv_layout(version_dir: Path, venv_name: str) -> Path:
    sub = "Scripts" if sys.platform == "win32" else "bin"
    exe = "python.exe" if sys.platform == "win32" else "python"
    py = version_dir / venv_name / sub / exe
    py.parent.mkdir(parents=True)
    py.write_text("", encoding="utf-8")
    return py


def test_python_exe_prefers_venv(tmp_path: Path) -> None:
    v1 = _make_venv_layout(tmp_path / "a", "venv")
    assert python_exe_for(tmp_path / "a") == v1


def test_python_exe_falls_back_to_dot_venv(tmp_path: Path) -> None:
    v2 = _make_venv_layout(tmp_path / "b", ".venv")
    assert python_exe_for(tmp_path / "b") == v2


def test_python_exe_prefers_venv_over_dot_venv(tmp_path: Path) -> None:
    v = _make_venv_layout(tmp_path / "c", "venv")
    _make_venv_layout(tmp_path / "c", ".venv")
    assert python_exe_for(tmp_path / "c") == v


def test_python_exe_missing_returns_panel_interpreter(tmp_path: Path) -> None:
    assert python_exe_for(tmp_path / "none") == Path(sys.executable)
