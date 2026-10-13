"""工作流管理器：官方库渠道（独立 Release）、本地上传、依赖模型清单解析。

不变量（docs/DOMAIN_MODEL.md「WorkflowItem」）：
- 本地文件只存在于共享工作流目录白名单内；
- 同 slug 重复导入 = 覆盖更新（保留 workflow_id，旧文件进 .history，留最近 5 份）；
- 导入/上传解析依赖清单并标注本机是否存在，不自动下载。
"""

from __future__ import annotations

import json
import re
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.core.config import read_json_with_backup, write_json_atomic
from app.core.errors import AppError
from app.core.paths import Layout
from app.infra.downloader import build_accel_env, download_file, fetch_json

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MODEL_EXT_RE = re.compile(
    r"\b[\w./\\\-]+\.(safetensors|sft|ckpt|pt|pth|bin|lora|vae|gguf)\b",
    re.IGNORECASE,
)
_CATEGORY_HINTS = {
    "checkpoints": "checkpoints",
    "diffusion_models": "diffusion_models",
    "unet": "diffusion_models",
    "controlnet": "controlnet",
    "loras": "loras",
    "lora": "loras",
    "text_encoders": "text_encoders",
    "clip": "clip",
    "vae": "vae",
    "upscale_models": "upscale_models",
    "embeddings": "embeddings",
}
_HISTORY_KEEP = 5


class LibraryEntry(BaseModel):
    slug: str
    name: str
    category: str = ""
    description: str = ""
    preview_url: str = ""
    models_required: list[str] = Field(default_factory=list)
    updated_at: str = ""
    file_url: str = ""
    sha256: str = ""


class LibraryIndex(BaseModel):
    channel: str = "launchpad-workflows"
    updated_at: str = ""
    workflows: list[LibraryEntry] = Field(default_factory=list)


class DependencyReportItem(BaseModel):
    model_file: str
    category: str
    present: bool
    suggest_dir: str


class WorkflowItem(BaseModel):
    workflow_id: str
    name: str
    source: str  # official | upload
    library_slug: str | None = None
    library_version: str | None = None
    file_path: str  # 相对共享工作流目录的文件名
    imported_at: str
    preview_url: str = ""
    dependency_report: list[DependencyReportItem] = Field(default_factory=list)


DEFAULT_WORKFLOWS_CHANNEL = (
    "https://github.com/REPLACE_ME/launchpad-workflows/releases"
)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def index_url_from_channel(channel_base: str) -> str:
    return f"{channel_base.rstrip('/')}/latest/download/workflows-index.json"


def sanitize_filename(name: str) -> str:
    name = Path(name).name
    name = re.sub(r"[^\w.\- \u4e00-\u9fff]", "_", name).strip()
    return name or "workflow.json"


def validate_workflow_json(text: str) -> dict[str, Any]:
    """ComfyUI 工作流格式校验（宽松）：UI 格式 / API 格式 / 嵌套 workflow 键。"""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AppError("invalid_workflow", f"JSON 解析失败: {exc}") from exc
    if not isinstance(data, dict):
        raise AppError("invalid_workflow", "顶层必须是 JSON 对象")
    if any(k in data for k in ("nodes", "workflow", "prompt")):
        return data
    # API 格式：{node_id: {class_type, inputs...}}
    values = [v for v in data.values() if isinstance(v, dict)]
    if data and values and all("class_type" in v for v in values):
        return data
    raise AppError(
        "invalid_workflow", "不是可识别的 ComfyUI 工作流（缺少 nodes/workflow/prompt 结构）"
    )


_SCAN_CACHE: dict[tuple[str, ...], tuple[float, dict[str, str]]] = {}
_SCAN_TTL_S = 60.0


def _present_index(roots: list[Path]) -> dict[str, str]:
    """多根目录的 文件名 → 分类 索引（60 秒缓存）。"""
    import time as _time

    key = tuple(str(r) for r in roots)
    now = _time.monotonic()
    cached = _SCAN_CACHE.get(key)
    if cached and now - cached[0] < _SCAN_TTL_S:
        return cached[1]
    present: dict[str, str] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for cat_dir in root.iterdir():
            if not cat_dir.is_dir():
                continue
            for f in cat_dir.rglob("*"):
                if f.is_file():
                    present.setdefault(f.name, cat_dir.name)
    _SCAN_CACHE[key] = (now, present)
    return present


def parse_dependencies(
    data: dict[str, Any],
    layout: Layout,
    extra_model_roots: list[Path] | None = None,
) -> list[DependencyReportItem]:
    """提取 JSON 中引用的模型文件名并对照全部模型根目录。

    扫描范围 = 面板共享布局 + extra_model_roots（数据盘公共模型/网盘/镜像自带），
    与 extra_model_paths.yaml 声明的 ComfyUI 可见范围保持一致。
    """
    found: dict[str, str] = {}  # basename -> category（首个提示优先）

    def walk(node: Any) -> None:
        if isinstance(node, str):
            for m in MODEL_EXT_RE.finditer(node):
                raw = m.group(0).replace("\\", "/")
                basename = raw.rsplit("/", 1)[-1]
                if basename in found:
                    continue
                category = "unknown"
                lowered = raw.lower()
                for hint, cat in _CATEGORY_HINTS.items():
                    if f"{hint}/" in lowered:
                        category = cat
                        break
                found[basename] = category
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            for v in node.values():
                walk(v)

    walk(data)

    # 扫描全部模型根目录建立 文件名 → 类别 索引（TTL 缓存，避免大目录反复遍历）
    roots = [layout.shared_models] + [Path(r) for r in (extra_model_roots or [])]
    present_map: dict[str, str] = _present_index(roots)

    items: list[DependencyReportItem] = []
    for basename, hinted_cat in sorted(found.items()):
        present = basename in present_map
        category = hinted_cat
        if category == "unknown" and present:
            category = present_map[basename]
        suggest = str(layout.shared_models / (category if category != "unknown" else "checkpoints"))
        items.append(
            DependencyReportItem(
                model_file=basename, category=category, present=present, suggest_dir=suggest
            )
        )
    return items


class WorkflowManager:
    def __init__(
        self,
        layout: Layout,
        channel_provider: Callable[[], str] | None = None,
    ) -> None:
        self._layout = layout
        self._channel_provider = channel_provider or (
            lambda: "https://github.com/REPLACE_ME/launchpad-workflows/releases"
        )
        self._registry_path = layout.state_dir / "workflows-registry.json"
        self._library_cache_path = layout.state_dir / "workflows-library-cache.json"
        # 工作流保存到 ComfyUI 用户目录侧（共享布局 user/default/workflows），
        # 使导入的工作流直接出现在 ComfyUI 界面的「工作流」侧边栏
        self._wf_dir = layout.shared_user / "default" / "workflows"
        self._legacy_dir = layout.shared_workflows
        self._migrate_legacy_files()

    def _model_roots(self) -> list[Path]:
        """ComfyUI 实际可见的全部模型根目录（与 extra_model_paths.yaml 对齐）。"""
        import sys as _sys

        roots = [self._layout.shared_models]
        if _sys.platform != "win32":
            roots.extend(
                Path(p)
                for p in (
                    "/root/autodl-tmp/models",
                    "/root/autodl-fs/models",
                    "/root/ComfyUI/models",
                )
            )
        return roots

    def _migrate_legacy_files(self) -> None:
        """一次性迁移：旧目录 shared/workflows 中的已登记文件移到新目录。"""
        if not self._legacy_dir.is_dir() or not self._registry_path.exists():
            return
        try:
            raw: dict[str, Any] = read_json_with_backup(self._registry_path)
            items: list[Any] = list(raw.get("items", []))
        except Exception:  # noqa: BLE001
            return
        self._wf_dir.mkdir(parents=True, exist_ok=True)
        changed = False
        for item in items:
            fp = item.get("file_path")
            if not fp:
                continue
            old = self._legacy_dir / fp
            new = self._wf_dir / fp
            if old.is_file() and not new.exists():
                new.parent.mkdir(parents=True, exist_ok=True)
                old.rename(new)
                changed = True
        if changed:
            write_json_atomic(self._registry_path, {"items": items})

    # ---------- 官方库 ----------

    async def refresh_library(self, accel_enabled: bool = False) -> LibraryIndex:

        accel_env = await asyncio_to_thread(build_accel_env, accel_enabled)
        url = index_url_from_channel(self._channel_provider())
        try:
            raw = await fetch_json(url, accel_env=accel_env)
        except AppError as exc:
            raise AppError(
                "index_unavailable", f"工作流库索引不可达：{exc.message}", status=502
            ) from exc
        data = LibraryIndex.model_validate(raw)
        write_json_atomic(
            self._library_cache_path,
            {"cached_at": _utcnow_iso(), **data.model_dump()},
        )
        return data

    def get_library(self) -> tuple[LibraryIndex | None, str | None, bool]:
        if not self._library_cache_path.exists():
            return None, None, True
        try:
            raw = read_json_with_backup(self._library_cache_path)
            data = LibraryIndex.model_validate(raw)
            cached_at = raw.get("cached_at")
            return data, str(cached_at) if cached_at else None, False
        except Exception:  # noqa: BLE001
            return None, None, True

    # ---------- 注册表 ----------

    def list_items(self) -> list[WorkflowItem]:
        if not self._registry_path.exists():
            return []
        try:
            raw: dict[str, Any] = read_json_with_backup(self._registry_path)
            items_raw: list[Any] = list(raw.get("items", []))
            return [WorkflowItem.model_validate(i) for i in items_raw]
        except Exception:  # noqa: BLE001
            return []

    def _save_registry(self, items: list[WorkflowItem]) -> None:
        write_json_atomic(
            self._registry_path, {"items": [i.model_dump() for i in items]}
        )

    # ---------- 导入 / 上传 / 删除 ----------

    async def import_official(self, slug: str, accel_enabled: bool = False) -> WorkflowItem:
        index, _, _ = self.get_library()
        if index is None:
            index = await self.refresh_library(accel_enabled)
        entry = next((w for w in index.workflows if w.slug == slug), None)
        if entry is None:
            raise AppError("invalid_workflow", f"官方库中不存在工作流 {slug}", status=404)

        accel_env = await asyncio_to_thread(build_accel_env, accel_enabled)
        filename = f"{sanitize_filename(slug)}.json"
        dest = self._wf_dir / filename
        await download_file(
            entry.file_url,
            dest_dir=dest.parent,
            filename=filename,
            expected_sha256=entry.sha256 or None,
            accel_env=accel_env,
        )
        return self._register(
            text=dest.read_text(encoding="utf-8", errors="replace"),
            filename=filename,
            source="official",
            name=entry.name,
            library_slug=slug,
            library_version=index.updated_at,
            preview_url=entry.preview_url,
        )

    def save_upload(self, filename: str, content: bytes) -> WorkflowItem:
        if len(content) > MAX_UPLOAD_BYTES:
            raise AppError("invalid_workflow", "文件超过 5MB 上限", status=400)
        if not filename.lower().endswith(".json"):
            raise AppError("invalid_workflow", "只接受 .json 文件", status=400)
        safe_name = sanitize_filename(filename)
        return self._register(
            text=content.decode("utf-8", errors="replace"),
            filename=safe_name,
            source="upload",
            name=Path(safe_name).stem,
            library_slug=None,
            library_version=None,
            preview_url="",
        )

    def _register(
        self,
        text: str,
        filename: str,
        source: str,
        name: str,
        library_slug: str | None,
        library_version: str | None,
        preview_url: str,
    ) -> WorkflowItem:
        data = validate_workflow_json(text)
        deps = parse_dependencies(data, self._layout, self._model_roots())

        items = self.list_items()
        existing = next(
            (i for i in items if (library_slug and i.library_slug == library_slug)
             or (library_slug is None and i.name == name and i.source == "upload")),
            None,
        )
        dest = self._wf_dir / filename
        dest.parent.mkdir(parents=True, exist_ok=True)

        if existing is not None:
            self._backup_old(existing.file_path)
            workflow_id = existing.workflow_id
            items.remove(existing)
        else:
            workflow_id = uuid.uuid4().hex[:12]

        dest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        item = WorkflowItem(
            workflow_id=workflow_id,
            name=name,
            source=source,
            library_slug=library_slug,
            library_version=library_version,
            file_path=filename,
            imported_at=_utcnow_iso(),
            preview_url=preview_url,
            dependency_report=deps,
        )
        items.append(item)
        self._save_registry(items)
        return item

    def delete(self, workflow_id: str) -> None:
        items = self.list_items()
        item = next((i for i in items if i.workflow_id == workflow_id), None)
        if item is None:
            raise AppError("invalid_workflow", f"工作流不存在: {workflow_id}", status=404)
        # 白名单内才删文件
        target = self._wf_dir / item.file_path
        try:
            resolved = target.resolve()
            in_whitelist = resolved.is_relative_to(self._wf_dir.resolve())
            if in_whitelist and resolved.is_file():
                resolved.unlink()
        except OSError:
            pass
        items.remove(item)
        self._save_registry(items)

    def _backup_old(self, file_path: str) -> None:
        old = self._wf_dir / file_path
        if not old.is_file():
            return
        history_dir = self._layout.workflow_history / Path(file_path).stem
        history_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        (history_dir / f"{ts}.json").write_bytes(old.read_bytes())
        backups = sorted(history_dir.glob("*.json"))
        for extra in backups[: -_HISTORY_KEEP]:
            extra.unlink(missing_ok=True)


async def asyncio_to_thread(func: Callable[..., Any], *args: Any) -> Any:
    import asyncio

    return await asyncio.to_thread(func, *args)
