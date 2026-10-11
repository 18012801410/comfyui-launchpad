#!/usr/bin/env bash
# ComfyUI LaunchPad 卸载脚本：停面板、删面板目录与 bashrc 片段；数据盘用户数据一律保留。
set -euo pipefail

LAUNCHPAD_DIR="${LAUNCHPAD_DIR:-/root/launchpad}"
MARKER_BEGIN="# >>> launchpad autostart >>>"
MARKER_END="# <<< launchpad autostart <<<"

log() { echo "[launchpad] $*"; }

# 停面板进程
if [ -f "$LAUNCHPAD_DIR/supervisor.sh" ]; then
  bash "$LAUNCHPAD_DIR/supervisor.sh" stop || true
fi

# 删面板目录（可重建）；数据盘 launchpad-data 保留
rm -rf "$LAUNCHPAD_DIR"
log "已删除 $LAUNCHPAD_DIR（数据目录 /root/autodl-tmp/launchpad-data 保留：版本/模型/输出/工作流均不受影响）"

# 清理 bashrc 自启片段
BASHRC="$HOME/.bashrc"
if [ -f "$BASHRC" ] && grep -qF "$MARKER_BEGIN" "$BASHRC"; then
  TMP="$(mktemp)"
  awk -v b="$MARKER_BEGIN" -v e="$MARKER_END" 'index($0,b){skip=1;next} index($0,e){skip=0;next} !skip' "$BASHRC" > "$TMP"
  mv "$TMP" "$BASHRC"
  log "已移除 ~/.bashrc 自启片段"
fi

log "卸载完成。如需重装，重新执行一键安装命令即可。"
