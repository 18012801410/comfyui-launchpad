#!/usr/bin/env bash
# LaunchPad 面板守护脚本：start/stop/restart/status/logs/is-running/switch。
# 自升级（switch <new_version_dir>）由面板后端调用：停旧→切链接→起新→健康检查→失败回滚。
set -euo pipefail

LAUNCHPAD_DIR="${LAUNCHPAD_DIR:-/root/launchpad}"
DATA_DIR="${LAUNCHPAD_DATA_DIR:-/root/autodl-tmp/launchpad-data}"
SUPERVISOR="$LAUNCHPAD_DIR/supervisor.sh"
PID_FILE="$DATA_DIR/state/panel.pid"
LOG_FILE="$DATA_DIR/logs/panel.log"
HEALTH_TIMEOUT=30

mkdir -p "$DATA_DIR/state" "$DATA_DIR/logs"

panel_port() {
  "$LAUNCHPAD_DIR/venv/bin/python" "$LAUNCHPAD_DIR/current/scripts/launchpad_cli.py" port 2>/dev/null || echo "6006"
}

panel_pid() {
  [ -f "$PID_FILE" ] && cat "$PID_FILE" 2>/dev/null || echo ""
}

alive() {
  local pid="$1"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

do_start() {
  if alive "$(panel_pid)"; then
    echo "already-running"
    return 0
  fi
  local port
  port="$(panel_port)"
  cd "$LAUNCHPAD_DIR/current/backend"
  nohup env LAUNCHPAD_DATA_DIR="$DATA_DIR" LAUNCHPAD_DIR="$LAUNCHPAD_DIR" \
    "$LAUNCHPAD_DIR/venv/bin/python" -m uvicorn app.main:app \
    --host 127.0.0.1 --port "$port" >>"$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"
  # 健康检查
  for _ in $(seq 1 "$HEALTH_TIMEOUT"); do
    if curl -sf "http://127.0.0.1:$port/panel/api/health" >/dev/null 2>&1; then
      echo "started"
      return 0
    fi
    sleep 1
  done
  echo "health-check-failed"
  return 1
}

do_stop() {
  local pid
  pid="$(panel_pid)"
  if alive "$pid"; then
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 15); do
      alive "$pid" || break
      sleep 1
    done
    alive "$pid" && kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$PID_FILE"
  echo "stopped"
}

do_status() {
  if alive "$(panel_pid)"; then echo "running"; else echo "stopped"; fi
}

do_switch() {
  # $1 = 新版本 staging 目录（自升级器已解压就位）；本命令负责落位→停旧→切换→健康检查→失败回滚
  local staging_dir="$1"
  local version new_dir old_target port
  version="$(basename "$staging_dir" | sed 's/\.staging$//')"
  new_dir="$LAUNCHPAD_DIR/releases/$version"
  old_target="$(readlink -f "$LAUNCHPAD_DIR/current" 2>/dev/null || true)"

  # 落位新版本（先清残留）
  rm -rf "$new_dir"
  mkdir -p "$LAUNCHPAD_DIR/releases"
  mv "$staging_dir" "$new_dir" || { echo "rolled-back:move-failed"; return 1; }

  do_stop >/dev/null
  ln -sfn "$new_dir" "$LAUNCHPAD_DIR/current"
  if do_start | grep -q "^started$"; then
    echo "switched:$version"
    # 清理旧版本目录（保留最近 2 个）
    (
      cd "$LAUNCHPAD_DIR/releases" 2>/dev/null || exit 0
      ls -1dt */ 2>/dev/null | tail -n +3 | while read -r old; do rm -rf "${old%/}"; done
    )
    return 0
  fi
  echo "switch-failed,rolling-back" >&2
  rm -rf "$new_dir"
  if [ -n "$old_target" ]; then
    ln -sfn "$old_target" "$LAUNCHPAD_DIR/current"
  fi
  do_start >/dev/null || true
  echo "rolled-back:$old_target"
  return 1
}

case "${1:-}" in
  start) do_start ;;
  stop) do_stop ;;
  restart) do_stop >/dev/null; do_start ;;
  status) do_status ;;
  is-running) alive "$(panel_pid)" ;;
  logs) tail -n 200 "$LOG_FILE" ;;
  switch)
    [ -n "${2:-}" ] || { echo "用法: supervisor.sh switch <新版本目录>"; exit 2; }
    do_switch "$2"
    ;;
  *)
    echo "用法: supervisor.sh start|stop|restart|status|is-running|logs|switch <dir>"
    exit 2
    ;;
esac
