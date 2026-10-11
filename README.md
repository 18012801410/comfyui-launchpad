# ComfyUI LaunchPad（ComfyUI 启动台）

运行在 AutoDL GPU 实例内的 ComfyUI 启动器控制面板：一键安装、网页启停 ComfyUI、多版本切换、插件更新、工作流导入、系统状态监控、面板自升级。

> 规格说明包见 [docs/](docs/)，项目状态见 [docs/PROJECT_STATE.md](docs/PROJECT_STATE.md)。

---

# 在 AutoDL 上部署启动

## 前置要求

- AutoDL 实例：**已挂载数据盘**（`/root/autodl-tmp` 存在）、Python ≥ 3.10、`curl`（基础镜像都有）
- 面板固定走 **6006 端口**（AutoDL「自定义服务」的公网映射端口）；如被占用安装脚本自动顺延 6008/6010
- 建议：实例直接选 **ComfyUI 应用镜像**（自带 ComfyUI + CUDA 环境，面板可直接纳管它）

## 安装后的自启动逻辑（重要，先读）

AutoDL 容器**没有 systemd**，实例开机后进程不会自动恢复。本面板的启动机制是：

```
实例开机 → 你第一次打开 SSH 或 JupyterLab 终端
        → ~/.bashrc 里的自启片段自动拉起面板（幂等，已在运行则跳过）
        → 面板常驻，之后随时可用
```

所以正确姿势是：**开机后随手开一个终端（JupyterLab 里点 Terminal 即可），面板就起来了**。卸载时这段会自动清除；不想自启就在安装时加 `LAUNCHPAD_NO_AUTOSTART=1`。

## 方式一：一键安装（面板正式发布后可用）

在实例终端执行（URL 以发布页为准）：

```bash
curl -fL https://github.com/<YOUR_REPO>/releases/latest/download/install.sh -o install.sh && bash install.sh
```

装完自动打印：**访问地址 + 访问令牌（只显示这一次，立即保存）**。

常用变体：

```bash
LAUNCHPAD_RESET=1 bash install.sh          # 重置令牌与配置
LAUNCHPAD_NO_AUTOSTART=1 bash install.sh   # 不写自启片段
bash /root/launchpad/supervisor.sh stop    # 停面板
bash /root/launchpad/supervisor.sh restart # 重启面板
bash /root/launchpad/supervisor.sh logs    # 看面板日志
bash scripts/uninstall.sh                  # 卸载（保留数据盘上的模型/输出/工作流）
```

## 方式二：源码直装（当前未发布 Release 时，现在就能用）

原理：把本仓库（含构建好的前端）上传到实例，用 `LAUNCHPAD_SOURCE` 模式安装，后续自启/管理方式和方式一完全一致。

**第 1 步 —— 开发机构建前端**（AutoDL 容器没有 Node.js，dist 要在本地构建好一起上传）：

```bash
cd frontend
npm install
npm run build        # 产出 frontend/dist
```

**第 2 步 —— 上传仓库到实例**。两种任选：

```bash
# A. scp 整个目录（替换成你的实例 SSH 信息，AutoDL 控制台可查）
scp -rP <端口> ./comfyui-setup-package root@<实例地址>:/root/launchpad-src

# B. 或推到你的 GitHub 私有仓库后，在实例里克隆（走学术加速更快）
source /etc/network_turbo
git clone https://github.com/<YOUR_REPO>.git /root/launchpad-src
```

**第 3 步 —— 实例内执行源码直装**：

```bash
cd /root/launchpad-src
LAUNCHPAD_SOURCE=/root/launchpad-src bash scripts/install.sh
```

脚本会：环境自检 → 复制源码到 `/root/launchpad/` → 建运行 venv 装依赖（自动走学术加速）→ 生成访问令牌 → 写 bashrc 自启 → 启动面板 → **打印访问地址与令牌**。

**第 4 步 —— 打开面板**：AutoDL 控制台 →「自定义服务」→ 复制 6006 端口的映射链接，浏览器打开，输入第 3 步打印的令牌。

## 让面板管住你的 ComfyUI

面板通过「版本目录 + current 符号链接」管理 ComfyUI。如果你用的是 **ComfyUI 应用镜像**（实例里已有 `/root/ComfyUI`），两条命令注册给面板：

```bash
D=/root/autodl-tmp/launchpad-data/versions
mkdir -p "$D"
ln -s /root/ComfyUI "$D/comfyui-app"                     # 注册已有安装
ln -sfn "$D/comfyui-app" "$D/current"                    # 设为当前版本
```

刷新面板首页 → 显示「运行中 comfyui-app」即可网页启停。（注意：应用镜像自带的 ComfyUI 若已被镜像机制启动，先在 JupyterLab 里 kill 掉旧进程再点面板「启动」，避免端口打架。）

没有现成 ComfyUI 时，等待版本渠道发布后直接在「版本管理」页一键安装（渠道地址在面板设置里配置）。

## 对外暴露 ComfyUI API（可选）

默认 ComfyUI 只监听本机。要给外部程序调用：面板首页 →「启动参数」→ 监听地址选「对外暴露（0.0.0.0）」、端口设 **6008**（AutoDL 第二个公网映射端口）→ 保存 → 重启 ComfyUI。外部基址即控制台里 6008 的映射域名：

```bash
curl https://<实例>-6008.seetacloud.com/system_stats        # 探活
curl -X POST .../prompt -d '{"prompt": <API格式工作流>}'      # 提交
curl .../history/<prompt_id>                                # 轮询
curl .../view?filename=xxx&type=output                      # 取图
```

> ⚠️ **ComfyUI 无内置鉴权**：拿到 URL 的任何人都能用你的 GPU。URL 务必保密；公开分发请等面板鉴权网关（二期）。

## 目录与数据安全

```
/root/launchpad/                      # 面板程序（可随时重装）
/root/autodl-tmp/launchpad-data/      # 一切数据：版本、共享模型/输出、工作流、配置、日志
```

卸载/重装只动 `/root/launchpad`；**模型、输出、工作流永远在数据盘上，不受影响**。

---

# 本地开发

```bash
# 后端（Python ≥3.10）
cd backend
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"        # Linux/macOS: .venv/bin/pip
.venv/Scripts/uvicorn app.main:app --port 6006

# 前端（Node ≥20）
cd frontend
npm install
npm run dev        # 开发服务器，/api 代理到 127.0.0.1:6006
npm run build      # 类型检查 + 构建到 dist/（后端自动挂载）
```

## 工程约定

- 后端：`ruff check . && mypy app && pytest` 全绿才算完成
- 前端：`npm run build`（含 vue-tsc 类型检查）全绿才算完成
- 每任务一提交，提交信息 `TASK-XXX: <一句话目标>`
- 领域层（`app/domain/`）禁止 import fastapi/httpx
