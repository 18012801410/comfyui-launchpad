"""工作流管理器测试：本地渠道导入、上传校验、依赖解析、历史备份、删除。"""

from __future__ import annotations

import hashlib
import http.server
import json
import socket
import threading
from pathlib import Path

import pytest

from app.core.errors import AppError
from app.domain.workflow_manager import (
    WorkflowManager,
    parse_dependencies,
    sanitize_filename,
    validate_workflow_json,
)


@pytest.fixture()
def static_server(tmp_path: Path):
    serve_dir = tmp_path / "www"
    serve_dir.mkdir()
    port = socket.socket()
    port.bind(("127.0.0.1", 0))
    port_no = int(port.getsockname()[1])
    port.close()

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, directory=str(serve_dir), **kwargs)  # type: ignore[arg-type]

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", port_no), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{port_no}", serve_dir
    server.shutdown()
    server.server_close()


UI_WORKFLOW = {
    "nodes": [
        {
            "id": 1,
            "type": "CheckpointLoaderSimple",
            "widgets_values": ["models/checkpoints/flux1-dev-fp8.safetensors"],
        },
        {"id": 2, "type": "LoraLoader", "widgets_values": ["loras/detail.safetensors", 0.8]},
        {"id": 3, "type": "KSampler"},
    ],
    "links": [],
}
API_WORKFLOW = {
    "1": {"class_type": "KSampler", "inputs": {"ckpt_name": "xl-base-1.0.safetensors"}},
}


def publish_workflow_library(serve_dir: Path, base: str) -> None:
    latest = serve_dir / "latest" / "download"
    latest.mkdir(parents=True, exist_ok=True)
    wf = serve_dir / "flux-portrait.json"
    wf.write_text(json.dumps(UI_WORKFLOW), encoding="utf-8")
    index = {
        "channel": "test",
        "updated_at": "2026-10-11T00:00:00Z",
        "workflows": [
            {
                "slug": "flux-portrait",
                "name": "Flux 人像",
                "category": "人像",
                "description": "示例",
                "preview_url": "",
                "models_required": [],
                "updated_at": "2026-10-10",
                "file_url": f"{base}/flux-portrait.json",
                "sha256": hashlib.sha256(wf.read_bytes()).hexdigest(),
            }
        ],
    }
    (latest / "workflows-index.json").write_text(json.dumps(index), encoding="utf-8")


def make_manager(layout, channel: str | None = None) -> WorkflowManager:
    return WorkflowManager(layout, channel_provider=lambda: channel or "unused")


def test_validate_workflow_formats() -> None:
    assert validate_workflow_json(json.dumps(UI_WORKFLOW))
    assert validate_workflow_json(json.dumps(API_WORKFLOW))
    with pytest.raises(AppError):
        validate_workflow_json("not json")
    with pytest.raises(AppError):
        validate_workflow_json(json.dumps({"foo": 1}))
    with pytest.raises(AppError):
        validate_workflow_json(json.dumps([1, 2]))


def test_parse_dependencies(layout) -> None:
    deps = parse_dependencies(UI_WORKFLOW, layout)
    names = {d.model_file for d in deps}
    assert "flux1-dev-fp8.safetensors" in names
    assert "detail.safetensors" in names
    ckpt = next(d for d in deps if d.model_file == "flux1-dev-fp8.safetensors")
    assert ckpt.category == "checkpoints"
    assert ckpt.present is False
    assert "checkpoints" in ckpt.suggest_dir


def test_sanitize_filename() -> None:
    assert sanitize_filename("../../evil.json") == "evil.json"
    assert sanitize_filename("我的 工作流.json") == "我的 工作流.json"
    assert sanitize_filename("a<b>.json") == "a_b_.json"


async def test_import_lands_in_comfyui_user_dir(layout, static_server) -> None:
    """验收核心：导入的文件必须出现在 ComfyUI 用户目录（侧边栏可见）。"""
    import http.server
    import socket
    import threading

    serve_dir = layout.shared_workflows.parent / "www"
    serve_dir.mkdir(parents=True, exist_ok=True)
    port = socket.socket()
    port.bind(("127.0.0.1", 0))
    port_no = int(port.getsockname()[1])
    port.close()

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, directory=str(serve_dir), **kwargs)  # type: ignore[arg-type]

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", port_no), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port_no}"
    latest = serve_dir / "latest" / "download"
    latest.mkdir(parents=True, exist_ok=True)
    wf = serve_dir / "t.json"
    wf.write_text(json.dumps(UI_WORKFLOW), encoding="utf-8")
    index = {"channel": "t", "updated_at": "x", "workflows": [
        {"slug": "t", "name": "T", "category": "", "description": "", "preview_url": "",
         "models_required": [], "updated_at": "", "file_url": f"{base}/t.json",
         "sha256": hashlib.sha256(wf.read_bytes()).hexdigest()}]}
    (latest / "workflows-index.json").write_text(json.dumps(index), encoding="utf-8")
    try:
        mgr = make_manager(layout, channel=base)
        await mgr.refresh_library()
        item = await mgr.import_official("t")
        # 新目录：shared/user/default/workflows（ComfyUI 侧边栏的数据源）
        assert (layout.shared_user / "default" / "workflows" / item.file_path).is_file()
    finally:
        server.shutdown()
        server.server_close()


async def test_legacy_migration_moves_files(layout) -> None:
    """旧目录文件 + 登记表 → 自动迁移到新目录。"""
    from app.core.config import write_json_atomic
    from app.domain.workflow_manager import WorkflowItem

    legacy = layout.shared_workflows
    legacy.mkdir(parents=True, exist_ok=True)
    (legacy / "old.json").write_text(json.dumps(UI_WORKFLOW), encoding="utf-8")
    item = WorkflowItem(
        workflow_id="abc123", name="old", source="upload", library_slug=None,
        library_version=None, file_path="old.json",
        imported_at="2026-10-11T00:00:00+00:00",
    )
    write_json_atomic(layout.state_dir / "workflows-registry.json",
                      {"items": [item.model_dump()]})
    mgr = make_manager(layout)
    items = mgr.list_items()
    assert len(items) == 1
    assert (layout.shared_user / "default" / "workflows" / "old.json").is_file()
    assert not (legacy / "old.json").exists()


async def test_import_official_flow(layout, static_server) -> None:
    base, serve_dir = static_server
    publish_workflow_library(serve_dir, base)
    mgr = make_manager(layout, channel=base)

    index = await mgr.refresh_library()
    assert index.workflows[0].slug == "flux-portrait"

    item = await mgr.import_official("flux-portrait")
    assert item.source == "official"
    assert item.library_slug == "flux-portrait"
    dest = layout.shared_user / "default" / "workflows" / item.file_path
    assert dest.is_file()
    assert any(d.model_file == "flux1-dev-fp8.safetensors" for d in item.dependency_report)

    # 已导入列表
    assert [i.workflow_id for i in mgr.list_items()] == [item.workflow_id]

    # 重复导入 = 覆盖（id 不变，历史备份生成）
    first_id = item.workflow_id
    item2 = await mgr.import_official("flux-portrait")
    assert item2.workflow_id == first_id
    history = list((layout.workflow_history / "flux-portrait").glob("*.json"))
    assert len(history) == 1


async def test_import_unknown_slug(layout, static_server) -> None:
    base, serve_dir = static_server
    publish_workflow_library(serve_dir, base)
    mgr = make_manager(layout, channel=base)
    await mgr.refresh_library()
    with pytest.raises(AppError) as ei:
        await mgr.import_official("nope")
    assert ei.value.code == "invalid_workflow"


def test_upload_delete_flow(layout) -> None:
    mgr = make_manager(layout)
    content = json.dumps(UI_WORKFLOW).encode("utf-8")
    item = mgr.save_upload("my workflow.json", content)
    assert item.source == "upload"
    assert (layout.shared_user / "default" / "workflows" / "my workflow.json").is_file()

    # 非 json 拒绝
    with pytest.raises(AppError):
        mgr.save_upload("evil.exe", b"mz")
    # 超限拒绝
    with pytest.raises(AppError):
        mgr.save_upload("big.json", b"x" * (6 * 1024 * 1024))
    # 坏格式拒绝
    with pytest.raises(AppError):
        mgr.save_upload("broken.json", b"{nope")

    mgr.delete(item.workflow_id)
    assert not (layout.shared_user / "default" / "workflows" / "my workflow.json").exists()
    assert mgr.list_items() == []

    with pytest.raises(AppError):
        mgr.delete(item.workflow_id)
