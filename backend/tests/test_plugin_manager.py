"""插件管理器测试：真实 git 仓库（本地 bare 远端）驱动扫描/检查/更新/启停。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.core.errors import AppError
from app.domain.plugin_manager import (
    check_update,
    scan_plugins,
    set_plugin_enabled,
    update_plugin,
)


def git(args: list[str], cwd: Path | None = None, check: bool = True) -> str:
    res = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        check=check,
        encoding="utf-8",
        errors="replace",
    )
    return res.stdout.strip()


def commit_file(repo: Path, filename: str, content: str, message: str) -> None:
    (repo / filename).write_text(content, encoding="utf-8")
    git(["add", "."], cwd=repo)
    git(["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", message], cwd=repo)


@pytest.fixture()
def plugin_repo(tmp_path: Path) -> tuple[Path, Path, Path]:
    """origin bare 仓库 + 一份 clone 到 custom_nodes，返回 (custom_nodes_dir, origin_bare)。"""
    origin = tmp_path / "origin.git"
    git(["init", "--bare", "-b", "main", str(origin)])
    work = tmp_path / "work"
    git(["clone", str(origin), str(work)])
    (work / "pyproject.toml").write_text(
        '[project]\nname = "fake-plugin"\ndescription = "一个测试插件"\n', encoding="utf-8"
    )
    commit_file(work, "plugin.py", "print('v1')\n", "v1")
    git(["push", "origin", "main"], cwd=work)

    custom_nodes = tmp_path / "version" / "custom_nodes"
    custom_nodes.mkdir(parents=True)
    plugin_dir = custom_nodes / "FakePlugin"
    git(["clone", str(origin), str(plugin_dir)])
    return custom_nodes, origin, work


def test_scan_plugins(plugin_repo: tuple[Path, Path, Path]) -> None:
    custom_nodes, _, _ = plugin_repo
    plugins = scan_plugins(custom_nodes)
    assert len(plugins) == 1
    p = plugins[0]
    assert p.name == "FakePlugin"
    assert p.enabled is True
    assert p.has_remote is True
    assert "描述" in p.summary or "测试" in p.summary
    assert p.git_ref


def test_update_flow(plugin_repo: tuple[Path, Path, Path]) -> None:
    custom_nodes, origin, work = plugin_repo
    # 状态初始应为 up_to_date
    assert check_update(custom_nodes, "FakePlugin") == "up_to_date"

    # 上游推进一个提交 → behind
    commit_file(work, "plugin.py", "print('v2')\n", "v2")
    git(["push", "origin", "main"], cwd=work)
    assert check_update(custom_nodes, "FakePlugin") == "behind"

    # 更新 → up_to_date 且内容推进
    message = update_plugin(custom_nodes, "FakePlugin")
    assert "已更新" in message
    assert check_update(custom_nodes, "FakePlugin") == "up_to_date"
    assert "v2" in (custom_nodes / "FakePlugin" / "plugin.py").read_text(encoding="utf-8")


def test_disable_enable(plugin_repo: tuple[Path, Path, Path]) -> None:
    custom_nodes, _, _ = plugin_repo
    msg = set_plugin_enabled(custom_nodes, "FakePlugin", enabled=False)
    assert "已禁用" in msg
    assert (custom_nodes / "FakePlugin.disabled").is_dir()
    plugins = scan_plugins(custom_nodes)
    assert plugins[0].enabled is False
    assert plugins[0].dir_name == "FakePlugin.disabled"

    msg2 = set_plugin_enabled(custom_nodes, "FakePlugin.disabled", enabled=True)
    assert "已启用" in msg2
    assert (custom_nodes / "FakePlugin").is_dir()


def test_update_non_git_rejected(tmp_path: Path) -> None:
    custom_nodes = tmp_path / "custom_nodes"
    custom_nodes.mkdir()
    (custom_nodes / "Manual").mkdir()
    with pytest.raises(AppError) as ei:
        update_plugin(custom_nodes, "Manual")
    assert ei.value.code == "plugin_update_failed"


def test_path_traversal_rejected(plugin_repo: tuple[Path, Path, Path]) -> None:
    custom_nodes, _, _ = plugin_repo
    with pytest.raises(AppError) as ei:
        update_plugin(custom_nodes, "../evil")
    assert ei.value.code == "path_forbidden"
