#!/usr/bin/env bash
# ComfyUI LaunchPad 一键部署到 AutoDL 实例（在开发机上运行，需 Git Bash/WSL/Linux）。
# 用法: bash scripts/deploy_autodl.sh <SSH端口> <用户@主机> [ComfyUI路径]
# 例:   bash scripts/deploy_autodl.sh 38888 root@connect.westc.gpuhub.com /root/ComfyUI
#
# 自动完成: 构建前端 → 打包 → scp 上传 → 实例内源码安装(装依赖/生成令牌/bashrc自启/启动面板)
#           → 注册实例已有 ComfyUI → 清理上传包。
# 前提: 实例已挂载数据盘(/root/autodl-tmp)；本机可直连实例 SSH。
set -euo pipefail

PORT="${1:?用法: deploy_autodl.sh <SSH端口> <用户@主机> [ComfyUI路径]}"
TARGET="${2:?缺少 用户@主机（见 AutoDL 控制台 SSH 登录指令）}"
COMFY_PATH="${3:-/root/ComfyUI}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REMOTE_DIR="/root/launchpad-src"

log() { echo "[deploy] $*"; }
SSH_OPTS=(-o StrictHostKeyChecking=no -o ServerAliveInterval=15)

# ---------- 1. 构建前端（AutoDL 无 Node，dist 必须本地构建随包上传） ----------
log "构建前端…"
( cd "$REPO_ROOT/frontend" && npm run build ) || { log "前端构建失败，终止"; exit 1; }

# ---------- 2. 打包（排除大目录与本地上传包） ----------
PACK="$REPO_ROOT/launchpad-upload.tar.gz"
log "打包 → $(basename "$PACK")"
tar --exclude='backend/.venv' \
    --exclude='frontend/node_modules' \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='launchpad-upload.tar.gz' \
    -czf "$PACK" -C "$REPO_ROOT" .

# ---------- 3. 上传 ----------
log "上传到 $TARGET:$PORT …"
scp -P "$PORT" "${SSH_OPTS[@]}" "$PACK" "$TARGET:/root/launchpad-upload.tar.gz"

# ---------- 4. 远端：安装 + 注册 ComfyUI + 清理 ----------
log "远端安装（依赖安装走学术加速，约 1-3 分钟）…"
ssh -p "$PORT" "${SSH_OPTS[@]}" "$TARGET" bash -s <<REMOTE
set -e
mkdir -p $REMOTE_DIR
tar xzf /root/launchpad-upload.tar.gz -C $REMOTE_DIR
cd $REMOTE_DIR
LAUNCHPAD_SOURCE=$REMOTE_DIR bash scripts/install.sh

D=/root/autodl-tmp/launchpad-data/versions
if [ -f "$COMFY_PATH/main.py" ]; then
  mkdir -p "\$D"
  ln -sfn "$COMFY_PATH" "\$D/comfyui-app"
  ln -sfn "\$D/comfyui-app" "\$D/current"
  echo ""
  echo "[deploy] 已注册 ComfyUI: $COMFY_PATH"
else
  echo ""
  echo "[deploy] 未找到 $COMFY_PATH/main.py，跳过 ComfyUI 注册（之后可在面板版本管理页安装）"
fi

rm -f /root/launchpad-upload.tar.gz
echo ""
echo "[deploy] 部署完成。打开 AutoDL 控制台 →「自定义服务」→ 复制 6006 端口映射链接，浏览器打开并输入上方令牌。"
REMOTE

log "完成。面板进程已常驻实例（重启实例后开一次 JupyterLab 终端即自动拉起）。"
