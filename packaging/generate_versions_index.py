"""生成 versions-index.json：合并构建 manifest → 渠道索引。

CI 用法: python packaging/generate_versions_index.py --manifests dist/ --out dist/versions-index.json
GITHUB_REPOSITORY 存在时替换 manifest 中的占位仓库地址。
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

REQUIRED_FIELDS = {"version", "sha256", "url", "size_mb"}
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def load_manifests(manifests_dir: Path) -> list[dict[str, Any]]:
    manifests: list[dict[str, Any]] = []
    for path in sorted(manifests_dir.glob("manifest-*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        validate_entry(raw, source=path.name)
        manifests.append(raw)
    return manifests


def validate_entry(entry: dict[str, Any], source: str = "") -> None:
    missing = REQUIRED_FIELDS - set(entry)
    if missing:
        raise ValueError(f"{source}: manifest 缺少字段 {sorted(missing)}")
    if not _VERSION_RE.match(str(entry["version"])):
        raise ValueError(f"{source}: version 不是语义化版本 {entry['version']}")
    if len(str(entry["sha256"])) != 64:
        raise ValueError(f"{source}: sha256 长度非法")


def substitute_repo_placeholder(entry: dict[str, Any]) -> dict[str, Any]:
    repo = os.environ.get("GITHUB_REPOSITORY")
    if repo:
        entry = dict(entry)
        for key in ("url",):
            val = str(entry.get(key, ""))
            entry[key] = val.replace("${GITHUB_REPOSITORY:-REPLACE_ME/launchpad-versions}", repo)
    return entry


def _version_key(entry: dict[str, Any]) -> tuple[int, int, int]:
    parts = [int(p) for p in str(entry["version"]).split(".")]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)  # type: ignore[return-value]


def build_index(manifests: list[dict[str, Any]]) -> dict[str, Any]:
    entries = [substitute_repo_placeholder(m) for m in manifests]
    entries.sort(key=_version_key, reverse=True)
    return {
        "channel": "launchpad-versions",
        "updated_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(timespec="seconds"),
        "versions": entries,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifests", required=True, help="manifest-*.json 所在目录")
    parser.add_argument("--out", required=True, help="输出的 versions-index.json 路径")
    args = parser.parse_args()

    manifests = load_manifests(Path(args.manifests))
    if not manifests:
        raise SystemExit("未找到任何 manifest-*.json")
    index = build_index(manifests)
    out = Path(args.out)
    out.write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"==> 索引已生成: {out} ({len(index['versions'])} 个版本)")


if __name__ == "__main__":
    main()
