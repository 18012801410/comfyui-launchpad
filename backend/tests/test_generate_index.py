"""索引生成器测试（packaging/generate_versions_index.py）。"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "gen_index",
        Path(__file__).parents[2] / "packaging" / "generate_versions_index.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_load_and_build_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load_module()
    (tmp_path / "manifest-0.3.39.json").write_text(
        json.dumps(
            {
                "version": "0.3.39",
                "size_mb": 500,
                "sha256": "a" * 64,
                "url": "https://x/${GITHUB_REPOSITORY:-REPLACE_ME/launchpad-versions}/releases/latest/download/a.tar.zst",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "manifest-0.3.30.json").write_text(
        json.dumps(
            {"version": "0.3.30", "size_mb": 490, "sha256": "b" * 64, "url": "https://x/b.tar.zst"}
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("GITHUB_REPOSITORY", "me/launchpad-versions")

    manifests = mod.load_manifests(tmp_path)
    index = mod.build_index(manifests)
    assert [v["version"] for v in index["versions"]] == ["0.3.39", "0.3.30"]
    # 仓库占位符被替换
    assert "${GITHUB_REPOSITORY" not in index["versions"][0]["url"]
    assert "me/launchpad-versions" in index["versions"][0]["url"]


def test_validate_rejects_bad_manifest(tmp_path: Path) -> None:
    mod = _load_module()
    bad = tmp_path / "manifest-bad.json"
    bad.write_text(
        json.dumps({"version": "not-semver", "sha256": "a" * 64, "url": "u", "size_mb": 1}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="语义化版本"):
        mod.load_manifests(tmp_path)

    bad2 = tmp_path / "manifest-bad2.json"
    bad2.write_text(
        json.dumps({"version": "1.0.0", "sha256": "short", "url": "u", "size_mb": 1}),
        encoding="utf-8",
    )
    # 单文件校验
    entry = json.loads(bad2.read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="sha256"):
        mod.validate_entry(entry, source="manifest-bad2.json")
