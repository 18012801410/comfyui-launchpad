#!/usr/bin/env bash
# 构建 ComfyUI 自包含版本包（在 Linux CI 上运行）。
# 用法: build_comfy_version.sh <version_tag> [torch_baseline]
# 环境变量: PYTHON_BIN（默认 python3）、PYTHON_ABI（默认 3.11，写入 manifest 供面板校验）
# 产物: dist/comfyui-<version>.tar.zst + dist/manifest-<version>.json
#
# ABI 约束（docs/TORCH_COMPAT.md）：包内 venv 的解释器指向构建机的基座 Python，
# 仅与同 ABI 的实例环境兼容（AutoDL 主流镜像为 miniconda 3.11）。
set -euo pipefail

VERSION_TAG="${1:?用法: build_comfy_version.sh <version_tag> [torch_baseline]}"
TORCH_BASELINE="${2:-${TORCH_BASELINE:-2.4.1}}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PYTHON_ABI="${PYTHON_ABI:-3.11}"

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT
DIST_DIR="${DIST_DIR:-dist}"
mkdir -p "$DIST_DIR"

echo "==> 克隆 ComfyUI v${VERSION_TAG}"
git clone --depth 1 --branch "v${VERSION_TAG}" https://github.com/comfyanonymous/ComfyUI.git \
  "$WORK_DIR/ComfyUI"

echo "==> 创建独立 venv（torch 复用镜像环境，不装 torch）"
"$PYTHON_BIN" -m venv "$WORK_DIR/venv"
PIP="$WORK_DIR/venv/bin/pip"
"$PIP" install --upgrade pip -q

# 过滤 torch 系列依赖（torch/torchvision/torchaudio 由宿主镜像提供）
grep -viE '^(torch|torchvision|torchaudio)([=<> !~;]|$)' \
  "$WORK_DIR/ComfyUI/requirements.txt" > "$WORK_DIR/requirements-filtered.txt" || true
"$PIP" install -r "$WORK_DIR/requirements-filtered.txt" -q

echo "==> 组装包内容"
PKG_ROOT="$WORK_DIR/pack/ComfyUI-$VERSION_TAG"
mkdir -p "$PKG_ROOT"
cp -r "$WORK_DIR/ComfyUI/." "$PKG_ROOT/"
rm -rf "$PKG_ROOT/.git"
cp -r "$WORK_DIR/venv" "$PKG_ROOT/venv"

echo "==> 打包 tar.zst"
tar --zstd -cf "$DIST_DIR/comfyui-${VERSION_TAG}.tar.zst" -C "$WORK_DIR/pack" "ComfyUI-$VERSION_TAG"

# GitHub Release 单文件上限 2GiB：超限自动切分为 1.9GB 分卷（.part00/.part01/…）
PKG="$DIST_DIR/comfyui-${VERSION_TAG}.tar.zst"
if [ "$(stat -c%s "$PKG")" -ge 2147483648 ]; then
  echo "==> 超 2GiB，切分分卷"
  split -b 1900M -d -a 2 "$PKG" "${PKG}.part"
  rm -f "$PKG"
fi

echo "==> 生成 manifest"
SHA256=$(sha256sum "$DIST_DIR/comfyui-${VERSION_TAG}.tar.zst" 2>/dev/null | cut -d' ' -f1)
SIZE_MB=$(( $(du -cm "$DIST_DIR"/comfyui-${VERSION_TAG}.tar.zst* 2>/dev/null | tail -1 | cut -f1) + 1 ))
# 分卷清单（未切分时为空数组）
PARTS_JSON="["
for f in "$DIST_DIR"/comfyui-${VERSION_TAG}.tar.zst.part*; do
  [ -e "$f" ] || continue
  PARTS_JSON="$PARTS\"$(basename "$f")\","
done
PARTS_JSON="${PARTS_JSON%,}]"
[ "$PARTS_JSON" = "]" ] && PARTS_JSON="[]"
cat > "$DIST_DIR/manifest-${VERSION_TAG}.json" <<EOF
{
  "version": "${VERSION_TAG}",
  "release_date": "$(date +%F)",
  "torch_baseline": "${TORCH_BASELINE}",
  "min_python": "3.10",
  "python_abi": "${PYTHON_ABI}",
  "size_mb": ${SIZE_MB},
  "sha256": "${SHA256}",
  "parts": ${PARTS_JSON},
  "url": "https://github.com/\${GITHUB_REPOSITORY:-REPLACE_ME/launchpad-versions}/releases/latest/download/comfyui-${VERSION_TAG}.tar.zst",
  "notes": "torch ${TORCH_BASELINE}（复用镜像环境，ABI ${PYTHON_ABI}）",
  "deprecated": false
}
EOF

echo "==> 完成: $DIST_DIR/comfyui-${VERSION_TAG}.tar.zst (sha256=${SHA256:0:12}…, ${SIZE_MB}MB)"
