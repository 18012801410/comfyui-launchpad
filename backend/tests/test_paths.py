"""safe_resolve 白名单校验测试：越界/绝对路径/symlink 逃逸全部拒绝。"""

import os
from pathlib import Path

import pytest

from app.core.paths import Layout, build_layout, safe_resolve


def test_safe_resolve_allows_inside(tmp_path: Path) -> None:
    base = tmp_path / "root"
    base.mkdir()
    assert safe_resolve(base, "sub/file.json") == Path(
        os.path.realpath(base / "sub/file.json")
    )


def test_safe_resolve_rejects_dotdot(tmp_path: Path) -> None:
    base = tmp_path / "root"
    base.mkdir()
    from app.core.paths import PathOutsideWhitelist

    with pytest.raises(PathOutsideWhitelist):
        safe_resolve(base, "../outside.txt")


def test_safe_resolve_rejects_absolute_outside(tmp_path: Path) -> None:
    base = tmp_path / "root"
    base.mkdir()
    from app.core.paths import PathOutsideWhitelist

    with pytest.raises(PathOutsideWhitelist):
        safe_resolve(base, str(tmp_path / "elsewhere" / "x.txt"))


def test_safe_resolve_rejects_symlink_escape(tmp_path: Path) -> None:
    base = tmp_path / "root"
    base.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = base / "link"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except OSError:
        pytest.skip("当前环境无 symlink 权限（Windows 非管理员）")
    from app.core.paths import PathOutsideWhitelist

    with pytest.raises(PathOutsideWhitelist):
        safe_resolve(base, "link/secret.txt")


def test_build_layout_defaults_and_ensure(tmp_path: Path) -> None:
    layout: Layout = build_layout(data_dir=str(tmp_path / "data"))
    layout.ensure()
    assert layout.versions_dir.is_dir()
    assert layout.shared_workflows.is_dir()
    assert (layout.shared_models / "checkpoints").is_dir()
    assert layout.current_link() == layout.versions_dir / "current"
