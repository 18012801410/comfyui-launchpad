#!/usr/bin/env bash
# 构建面板发行包：前端产物 + 后端 + 脚本 + 渠道样例 → launchpad-<version>.tar.zst
# 用法: bash packaging/build_panel.sh <version>   （version 如 2026.10.11 或 0.1.0）
# 产物: dist/launchpad-<version>.tar.zst + dist/manifest-panel-<version>.json
set -euo pipefail

VERSION="${1:?用法: build_panel.sh <version>}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST_DIR="${DIST_DIR:-$REPO_ROOT/dist}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "==> 构建前端"
( cd "$REPO_ROOT/frontend" && npm ci --no-fund --no-audit && npm run build )

echo "==> 组装包内容"
PKG="$WORK/pkg"
mkdir -p "$PKG"
cp -r "$REPO_ROOT/backend" "$PKG/backend"
rm -rf "$PKG/backend/.venv" "$PKG/backend/.pytest_cache" "$PKG/backend/.mypy_cache" "$PKG/backend/.ruff_cache"
find "$PKG/backend" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
cp -r "$REPO_ROOT/frontend/dist" "$PKG/frontend-dist"
cp -r "$REPO_ROOT/scripts" "$PKG/scripts"
mkdir -p "$PKG/channels"
cp "$REPO_ROOT"/channels/*.json "$PKG/channels/" 2>/dev/null || true
printf '{"version": "%s"}\n' "$VERSION" > "$PKG/version.json"

echo "==> 打包 tar.zst"
mkdir -p "$DIST_DIR"
tar --zstd -cf "$DIST_DIR/launchpad-${VERSION}.tar.zst" -C "$PKG" .

echo "==> 生成 manifest"
SHA256=$(sha256sum "$DIST_DIR/launchpad-${VERSION}.tar.zst" | cut -d' ' -f1)
SIZE_MB=$(( $(stat -c%s "$DIST_DIR/launchpad-${VERSION}.tar.zst") / 1024 / 1024 + 1 ))
cat > "$DIST_DIR/manifest-panel-${VERSION}.json" <<EOF
{
  "version": "${VERSION}",
  "notes": "面板发行版 ${VERSION}",
  "sha256": "${SHA256}",
  "url": "https://github.com/\${GITHUB_REPOSITORY:-REPLACE_ME/launchpad-panel}/releases/latest/download/launchpad-${VERSION}.tar.zst",
  "published_at": "$(date -u +%FT%TZ)",
  "size_mb": ${SIZE_MB}
}
EOF
echo "==> 完成: $DIST_DIR/launchpad-${VERSION}.tar.zst (sha256=${SHA256:0:12}…)"
