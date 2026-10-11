"""extra_model_paths.yaml 生成测试（对接 AutoDL 模型生态，对标参考实例挂载方式）。"""

from __future__ import annotations

from pathlib import Path

from app.domain.version_manager import (
    build_extra_model_paths_yaml,
    ensure_shared_links,
    write_extra_model_paths,
)


def test_yaml_contains_three_sections(tmp_path: Path, layout) -> None:
    yaml_text = build_extra_model_paths_yaml(layout)
    assert "launchpad:" in yaml_text
    assert "autodl_tmp:" in yaml_text
    assert "autodl_fs:" in yaml_text
    assert f"base_path: {layout.shared_models.as_posix()}" in yaml_text
    assert "base_path: /root/autodl-tmp/models" in yaml_text
    assert "base_path: /root/autodl-fs/models" in yaml_text
    # 关键分类齐全
    for cat in ("checkpoints", "loras", "diffusion_models", "text_encoders", "vae"):
        assert f"    {cat}: {cat}" in yaml_text


def test_yaml_is_parseable_and_sections_have_categories(tmp_path: Path, layout) -> None:
    import yaml  # pyyaml 由 ComfyUI 侧使用；开发环境验证格式

    data = yaml.safe_load(build_extra_model_paths_yaml(layout))
    assert set(data.keys()) == {"launchpad", "autodl_tmp", "autodl_fs"}
    for section in data.values():
        assert section["base_path"]
        assert section["checkpoints"] == "checkpoints"


def test_write_creates_and_never_overwrites(tmp_path: Path, layout) -> None:
    vdir = tmp_path / "v0.1"
    vdir.mkdir()
    written = write_extra_model_paths(vdir, layout)
    assert written is not None and written.is_file()
    # 用户自配保护：已存在则不动
    (vdir / "extra_model_paths.yaml").write_text("my_own: true", encoding="utf-8")
    assert write_extra_model_paths(vdir, layout) is None
    assert (vdir / "extra_model_paths.yaml").read_text(encoding="utf-8") == "my_own: true"


def test_ensure_shared_links_writes_yaml(tmp_path: Path, layout) -> None:
    vdir = tmp_path / "v0.2"
    vdir.mkdir()
    (vdir / "main.py").write_text("#", encoding="utf-8")
    ensure_shared_links(vdir, layout)
    assert (vdir / "extra_model_paths.yaml").is_file()
