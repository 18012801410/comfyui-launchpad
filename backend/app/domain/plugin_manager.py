"""插件管理器（轻量）：扫描 custom_nodes、git 更新、启用/禁用（目录后缀法）。

范围决策（FR-008）：不做市场/搜索/依赖修复；插件按版本存放（custom_nodes 不共享，
代码兼容性优先）；启用/禁用 = 目录名加 `.disabled` 后缀，重启 ComfyUI 生效。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.errors import AppError
from app.core.paths import PathOutsideWhitelist, safe_resolve
from app.infra.shell import ShellCommandError, run_cmd

_DISABLED_SUFFIX = ".disabled"


@dataclass
class PluginInfo:
    name: str
    dir_name: str  # 含 .disabled 后缀的真实目录名
    enabled: bool
    summary: str = ""
    git_url: str = ""
    git_ref: str = ""
    update_status: str = "unknown"  # up_to_date | behind | unknown
    has_remote: bool = False

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _read_summary(plugin_dir: Path) -> str:
    """读 pyproject.toml description，回退 README 首段，再回退空。"""
    pyproject = plugin_dir / "pyproject.toml"
    if pyproject.is_file():
        try:
            import tomllib  # noqa: PLC0415

            data = tomllib.loads(pyproject.read_text(encoding="utf-8", errors="replace"))
            desc = data.get("project", {}).get("description")
            if desc:
                return str(desc)[:200]
        except Exception:  # noqa: BLE001 - 元数据读取失败不致命
            pass
    for readme in ("README.md", "readme.md", "README.txt"):
        f = plugin_dir / readme
        if f.is_file():
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
                text = re.sub(r"[#>*`\[\]]", "", text)
                text = re.sub(r"\s+", " ", text).strip()
                if text:
                    return text[:200]
            except OSError:
                continue
    return ""


def _git_dir(plugin_dir: Path) -> bool:
    return (plugin_dir / ".git").exists()


def scan_plugins(custom_nodes_dir: Path) -> list[PluginInfo]:
    """扫描插件目录；单插件元数据失败不影响整体。"""
    if not custom_nodes_dir.is_dir():
        return []
    plugins: list[PluginInfo] = []
    for child in sorted(custom_nodes_dir.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        enabled = not child.name.endswith(_DISABLED_SUFFIX)
        display = child.name[: -len(_DISABLED_SUFFIX)] if not enabled else child.name
        info = PluginInfo(
            name=display, dir_name=child.name, enabled=enabled, summary=_read_summary(child)
        )
        if _git_dir(child):
            try:
                url = run_cmd(
                    ["git", "-C", str(child), "remote", "get-url", "origin"],
                    check=False,
                )
                info.git_url = url.stdout.strip()
                info.has_remote = bool(info.git_url)
                ref = run_cmd(
                    ["git", "-C", str(child), "rev-parse", "--short", "HEAD"],
                    check=False,
                )
                info.git_ref = ref.stdout.strip()
            except ShellCommandError:
                pass
        plugins.append(info)
    return plugins


def safe_plugin_dir(custom_nodes_dir: Path, dir_name: str) -> Path:
    try:
        resolved = safe_resolve(custom_nodes_dir, dir_name)
    except PathOutsideWhitelist as exc:
        raise AppError("path_forbidden", str(exc), status=403) from exc
    if not resolved.is_dir():
        raise AppError("path_forbidden", f"插件目录不存在: {dir_name}", status=404)
    return resolved


def check_update(custom_nodes_dir: Path, dir_name: str) -> str:
    """检查更新状态：fetch 后比较 HEAD 与上游。失败 → unknown（插件保持可用）。"""
    plugin_dir = safe_plugin_dir(custom_nodes_dir, dir_name)
    if not _git_dir(plugin_dir):
        return "unknown"
    try:
        run_cmd(["git", "-C", str(plugin_dir), "fetch", "--quiet", "origin"], timeout_s=30)
        behind = run_cmd(
            ["git", "-C", str(plugin_dir), "rev-list", "--count", "HEAD..@{u}"],
            check=False,
            timeout_s=15,
        )
        count = behind.stdout.strip()
        return "behind" if count.isdigit() and int(count) > 0 else "up_to_date"
    except ShellCommandError:
        return "unknown"


def update_plugin(custom_nodes_dir: Path, dir_name: str) -> str:
    """一键更新 = git pull --ff-only（失败不动树，插件保持可用）。"""
    plugin_dir = safe_plugin_dir(custom_nodes_dir, dir_name)
    if not _git_dir(plugin_dir):
        raise AppError(
            "plugin_update_failed",
            f"插件 {dir_name} 不是 git 安装（无 .git），请手动更新",
            status=400,
        )
    try:
        res = run_cmd(["git", "-C", str(plugin_dir), "pull", "--ff-only"], timeout_s=120)
        out = res.stdout.strip()
        ref = run_cmd(["git", "-C", str(plugin_dir), "rev-parse", "--short", "HEAD"], check=False)
        return f"已更新到 {ref.stdout.strip()}" if out else f"已是最新 {ref.stdout.strip()}"
    except ShellCommandError as exc:
        raise AppError(
            "plugin_update_failed",
            f"插件 {dir_name} 更新失败（已回滚保持可用）：{str(exc)[:200]}",
            status=500,
        ) from exc


def set_plugin_enabled(custom_nodes_dir: Path, dir_name: str, enabled: bool) -> str:
    """启用/禁用：目录改名（± .disabled 后缀），重启 ComfyUI 生效。"""
    plugin_dir = safe_plugin_dir(custom_nodes_dir, dir_name)
    if enabled:
        if not plugin_dir.name.endswith(_DISABLED_SUFFIX):
            return f"插件 {dir_name} 已是启用状态"
        target = plugin_dir.with_name(plugin_dir.name[: -len(_DISABLED_SUFFIX)])
        if target.exists():
            raise AppError(
                "path_forbidden",
                f"启用失败：目标目录已存在 {target.name}",
                status=409,
            )
        plugin_dir.rename(target)
        return f"已启用 {target.name}，重启 ComfyUI 后生效"
    else:
        if plugin_dir.name.endswith(_DISABLED_SUFFIX):
            return f"插件 {dir_name} 已是禁用状态"
        target = plugin_dir.with_name(plugin_dir.name + _DISABLED_SUFFIX)
        if target.exists():
            raise AppError("path_forbidden", "禁用失败：后缀目录已存在", status=409)
        plugin_dir.rename(target)
        return f"已禁用 {plugin_dir.name}，重启 ComfyUI 后生效"
