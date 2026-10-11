# 技术规格（Technical Specification）

## 技术栈

| 领域 | 选择 | 原因 |
|---|---|---|
| 后端 | Python 3.10+ / FastAPI / uvicorn（单 worker）/ Pydantic v2 | AutoDL 自带；SSE 原生支持；类型化契约 |
| 前端 | Vue 3 + Vite + TypeScript + Pinia + Vue Router | 构建产物纯静态；暗色主题用 CSS variables |
| 数据库 | 无（JSON 原子写；SQLite 备选预案） | 规模不需要；见 ARCHITECTURE 决策 |
| 存储 | 本地文件系统（数据盘白名单目录） | AutoDL 数据盘 |
| 进程 | asyncio.subprocess（ComfyUI）；bash supervisor（面板自升级/自启） | 容器无 systemd（已核实） |
| CI | GitHub Actions：前端构建 → 后端打包 → 版本包矩阵构建 → Releases | 与分发渠道同栈 |
| 测试 | pytest（领域层单测）+ httpx TestClient（API）+ 前端 Vitest（关键组件） | 领域逻辑必须可测 |

## 仓库结构

```
comfyui-launchpad/
├─ backend/
│  └─ app/
│     ├─ main.py            # FastAPI 装配（应用壳）
│     ├─ core/              # config, events, security(令牌), paths(白名单)
│     ├─ domain/            # 纯领域：process_supervisor, version_manager,
│     │                     #          plugin_manager, workflow_manager,
│     │                     #          self_updater, sysinfo
│     ├─ infra/             # downloader(提供方适配), shell(git/nvidia-smi 封装)
│     └─ api/               # 路由层：auth, comfy, versions, plugins,
│                           #         workflows, system, selfupdate, sse
│  └─ tests/
├─ frontend/
│  ├─ src/{views,components,stores,api,styles}
│  └─ dist/                 # 构建产物（后端挂载）
├─ scripts/
│  ├─ install.sh / uninstall.sh
│  ├─ supervisor.sh         # 面板自启拉起 + 自升级接管
│  └─ launchpad             # 管理命令 start/stop/status/logs
├─ packaging/
│  ├─ build_panel.sh        # 面板发行包（backend+dist+scripts → tar.zst）
│  └─ build_comfy_version.sh# CI 用：ComfyUI 版本包构建（矩阵）
├─ channels/
│  ├─ versions-index.json   # 版本渠道索引样例（schema 权威在此）
│  └─ workflows-index.json  # 工作流渠道索引样例
├─ docs/                    # 本规格包
└─ .github/workflows/{release-panel.yml, build-versions.yml}
```

**归属**：`backend/app/domain` 不 import fastapi/http（纯领域，可测）；API 层只做校验与编排；UI 只消费契约。

## 运行环境

- **开发**：Windows/WSL 或任意 Linux；后端可裸跑（sysinfo 降级为 mock）；前端 Vite dev server 代理 API。
- **目标生产**：AutoDL 容器（Ubuntu 20.04/22.04，conda Python 3.10/3.11，CUDA 11.8/12.x，无 systemd，用户 root）。
- **预发布**：作者自己的 AutoDL 实例（真实环境冒烟）。

## 基础设施

- GitHub Releases ×2 渠道：`panel`（面板发行包+index.json）、`versions`（ComfyUI 版本包+index.json）、工作流库独立仓库同构。
- 目录布局（白名单常量，集中在 `core/paths.py`）：

```
/root/launchpad/                     # 面板自身（可重建）
  releases/<v>/…                     # 各面板版本
  current -> releases/<v>            # 面板符号链接
  supervisor.sh
/root/autodl-tmp/launchpad-data/     # 数据盘（一切大文件与状态）
  versions/<ver>/                    # ComfyUI 版本实例
  versions/.staging/…                # 下载/解压临时区（原子 rename 源）
  shared/{models,output,input,user,workflows}
  state/{config.json,versions-state.json,workflows-registry.json}
  logs/{panel.log,comfy.<ts>.log}
  panel-releases/                    # 自升级下载暂存
```

## 配置/环境变量

config.json（PanelSettings，见 DOMAIN_MODEL）为主；环境变量仅安装/运维用：
- `LAUNCHPAD_PORT`（默认 6006，占用则顺延 6008→6010…）
- `LAUNCHPAD_NO_AUTOSTART=1`（安装时不注入 bashrc）
- `LAUNCHPAD_RESET=1`（重装时重置令牌与配置）
- `LAUNCHPAD_DATA_DIR`（默认 `/root/autodl-tmp/launchpad-data`，允许无数据盘的开发环境覆盖）

学术加速：`source /etc/network_turbo`（存在才执行）；降级 = `unset http_proxy https_proxy all_proxy`。

## 第三方依赖

后端运行时仅：fastapi、uvicorn、pydantic、httpx、zstandard（解压）。**刻意不依赖**：docker、torch（运行时不 import）、sqlite（预案除外）。前端：vue、vue-router、pinia、axios（或 fetch 封装）。安装脚本运行时依赖：curl、python、tar、git（插件更新用，缺失则插件更新功能降级提示）。

## 部署

**首次安装**（install.sh，幂等）：
1. 环境自检（python≥3.10、数据盘存在、磁盘余量、端口探测）。
2. 下载面板发行包 → `/root/launchpad/releases/<v>/`（原子 rename）。
3. 初始化数据盘目录与 config.json（生成令牌，打印一次明文）。
4. 写 supervisor.sh + bashrc 注入片段（幂等标记块）。
5. `launchpad start` → 打印访问 URL（AutoDL 6006 映射域名规则提示）与令牌。

**自升级**：见 ARCHITECTURE 数据流；supervisor.sh 提供 `switch <new_v>` 子命令（停旧→切链接→起新→健康检查→失败回滚）。

**卸载**：uninstall.sh 停进程 → 删 `/root/launchpad` → 移除 bashrc 标记块 → 数据盘目录保留并打印保留路径。

## 可观测性

- 日志：panel.log（结构化行：时间/级别/模块/事件）+ comfy.<ts>.log（原样 stdout/stderr）；环形缓冲各 2000 行供页面即时查看。
- 指标：/api/system/status 快照（GPU/内存/磁盘/进程）；下载进度事件。
- 追踪：无（单机单用户，MVP 不引入）。
- 告警：无服务端告警；页面内错误横幅 + 日志页 ERROR 高亮。

## 安全

- 认证：Bearer 令牌（32 字符 secrets.token_urlsafe）；服务端只存盐哈希；除回环 `/api/health` 外全拦截；静态页面壳可加载（无敏感数据），API 一律 401。
- 授权：单管理员模型，无角色。
- 密钥：无第三方密钥；渠道 URL 非机密可公开。
- 数据保护：路径白名单 + realpath 校验防穿越；命令参数禁 shell=True（git/nvidia-smi 用参数数组）；上传文件限 5MB 与 .json 扩展；日志脱敏令牌；CORS 默认关闭（同源）。
- 子进程：ComfyUI 以实例用户运行、进程组管理、无提权；启动参数字符白名单。
