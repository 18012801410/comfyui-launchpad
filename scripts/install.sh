#!/usr/bin/env bash
# ComfyUI LaunchPad 一键安装脚本（幂等，可重复执行=升级面板）。
# 用法: bash install.sh
# 环境变量:
#   LAUNCHPAD_CHANNEL   面板发行渠道基址（默认官方仓库 Releases）
#   LAUNCHPAD_PORT      面板端口（默认 6006，被占用自动顺延 6008/6010/6012）
#   LAUNCHPAD_NO_AUTOSTART=1   跳过写入 ~/.bashrc 自启片段
#   LAUNCHPAD_RESET=1   重装时重置令牌与配置
set -euo pipefail

LAUNCHPAD_DIR="${LAUNCHPAD_DIR:-/root/launchpad}"
DATA_DIR="${LAUNCHPAD_DATA_DIR:-/root/autodl-tmp/launchpad-data}"
CHANNEL="${LAUNCHPAD_CHANNEL:-https://github.com/REPLACE_ME/launchpad-panel/releases}"
PANEL_PORT="${LAUNCHPAD_PORT:-6006}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
MARKER_BEGIN="# >>> launchpad autostart >>>"
MARKER_END="# <<< launchpad autostart <<<"

log() { echo "[launchpad] $*"; }
fail() { echo "[launchpad] 错误: $*" >&2; exit 1; }

# ---------- 1. 环境自检 ----------
command -v "$PYTHON_BIN" >/dev/null || fail "未找到 $PYTHON_BIN，请使用带 Python 的镜像"
PY_VERSION=$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')
"$PYTHON_BIN" - "$PY_VERSION" <<'EOF' || fail "需要 Python ≥ 3.10"
import sys
major, minor = (int(x) for x in sys.argv[1].split("."))
sys.exit(0 if (major, minor) >= (3, 10) else 1)
EOF
log "Python ${PY_VERSION} ✓"

if [ ! -d /root/autodl-tmp ]; then
  fail "未检测到数据盘 /root/autodl-tmp，请先在 AutoDL 控制台为实例挂载数据盘"
fi
FREE_KB=$(df -k /root/autodl-tmp | tail -1 | awk '{print $4}')
if [ "$FREE_KB" -lt $(( 2 * 1024 * 1024 )) ]; then
  fail "数据盘剩余空间不足 2GB，请先清理"
fi
log "数据盘空间 ✓ ($(( FREE_KB / 1024 / 1024 )) GB 可用)"

# 端口探测：占用则顺延（最多 4 次）
port_busy() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null && { exec 3>&- 3<&-; return 0; } || return 1; }
TRY_PORT="$PANEL_PORT"
for CAND in 6006 6008 6010 6012; do
  if ! port_busy "$CAND"; then TRY_PORT="$CAND"; break; fi
  [ "$CAND" = "6012" ] && fail "6006/6008/6010/6012 全部被占用，请释放端口"
done
if [ "$TRY_PORT" != "$PANEL_PORT" ]; then
  log "端口 $PANEL_PORT 被占用，自动改用 $TRY_PORT"
fi
PANEL_PORT="$TRY_PORT"

# ---------- 2. 下载面板发行包 ----------
mkdir -p "$LAUNCHPAD_DIR/releases" "$DATA_DIR"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
log "下载面板发行包…"
PKG_URL="$CHANNEL/latest/download/launchpad.tar.zst"
if command -v curl >/dev/null; then
  # 加速可开可关：失败自动降级直连
  if [ -f /etc/network_turbo ]; then
    # shellcheck disable=SC1091
    source /etc/network_turbo || true
  fi
  curl -fL --retry 2 --connect-timeout 15 -o "$WORK/launchpad.tar.zst" "$PKG_URL" \
    || { unset http_proxy https_proxy all_proxy; curl -fL --retry 1 --connect-timeout 15 -o "$WORK/launchpad.tar.zst" "$PKG_URL"; }
else
  fail "未找到 curl"
fi

NEW_DIR="$WORK/panel"
mkdir -p "$NEW_DIR"
tar --zstd -xf "$WORK/launchpad.tar.zst" -C "$NEW_DIR" --strip-components=1
[ -f "$NEW_DIR/backend/app/main.py" ] || fail "发行包结构异常（缺少 backend/app/main.py）"

VERSION=$("$PYTHON_BIN" -c "import json,sys;print(json.load(open('$NEW_DIR/version.json'))['version'])" 2>/dev/null \
  || echo "$(date +%Y%m%d%H%M)")
TARGET="$LAUNCHPAD_DIR/releases/$VERSION"
rm -rf "$TARGET"
mkdir -p "$TARGET"
cp -r "$NEW_DIR/." "$TARGET/"
ln -sfn "$TARGET" "$LAUNCHPAD_DIR/current"
log "面板 $VERSION 已就位于 $TARGET"

# ---------- 3. 面板运行 venv ----------
if [ ! -x "$LAUNCHPAD_DIR/venv/bin/python" ]; then
  log "创建面板运行环境…"
  "$PYTHON_BIN" -m venv "$LAUNCHPAD_DIR/venv"
  "$LAUNCHPAD_DIR/venv/bin/pip" install --upgrade pip -q
fi
if [ -f /etc/network_turbo ]; then
  # shellcheck disable=SC1091
  source /etc/network_turbo || true
fi
"$LAUNCHPAD_DIR/venv/bin/pip" install -q -r "$TARGET/backend/requirements.txt" \
  || { unset http_proxy https_proxy all_proxy; "$LAUNCHPAD_DIR/venv/bin/pip" install -q -r "$TARGET/backend/requirements.txt"; }
log "面板依赖 ✓"

# ---------- 4. 初始化配置 / 令牌 ----------
export LAUNCHPAD_DATA_DIR="$DATA_DIR" LAUNCHPAD_DIR LAUNCHPAD_PORT
INIT_OUT=$("$LAUNCHPAD_DIR/venv/bin/python" "$LAUNCHPAD_DIR/current/scripts/launchpad_cli.py" init ${LAUNCHPAD_RESET:+--reset} --port "$PANEL_PORT")
TOKEN=$(echo "$INIT_OUT" | tail -1)

# ---------- 5. 写 bashrc 自启片段（幂等） ----------
if [ "${LAUNCHPAD_NO_AUTOSTART:-0}" != "1" ]; then
  BASHRC="$HOME/.bashrc"
  touch "$BASHRC"
  if ! grep -qF "$MARKER_BEGIN" "$BASHRC"; then
    cat >> "$BASHRC" <<EOF
$MARKER_BEGIN
if [ -x "$LAUNCHPAD_DIR/supervisor.sh" ] && ! "$LAUNCHPAD_DIR/supervisor.sh" is-running >/dev/null 2>&1; then
  nohup bash "$LAUNCHPAD_DIR/supervisor.sh" start >/dev/null 2>&1 &
fi
$MARKER_END
EOF
    log "已写入 ~/.bashrc 自启片段（SSH 登录时自动拉起面板）"
  fi
fi

# ---------- 6. 启动面板 ----------
bash "$LAUNCHPAD_DIR/supervisor.sh" restart

# ---------- 7. 打印访问信息 ----------
PUBLIC_HOST="${AUTO_DL_PUBLIC_HOST:-<你的实例:6006 端口映射域名>}"
log "=============================================="
log "安装完成！面板版本: $VERSION"
log "本机地址: http://127.0.0.1:$PANEL_PORT"
log "公网地址: 在 AutoDL 控制台「自定义服务」查看 $PANEL_PORT 端口映射的 https 域名"
log "访问令牌: $TOKEN"
log "令牌只显示这一次，请立即保存（可在面板设置中重新生成）"
log "管理命令: bash $LAUNCHPAD_DIR/supervisor.sh start|stop|restart|status|logs"
log "=============================================="
