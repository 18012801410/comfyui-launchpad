# 架构（Architecture）

> 上游：docs/PROJECT_BRIEF.md、docs/REQUIREMENTS.md ｜ 日期：2026-10-11

## 1. 系统概览

ComfyUI LaunchPad 是一个**单实例内嵌面板**：全部软件运行在用户租用的 AutoDL GPU 容器内，通过 AutoDL 的端口映射（默认 6006 → 公网 HTTPS 域名）对外服务一个浏览器界面。面板后端既是 Web 服务器，也是 ComfyUI 进程的监督者，还是版本包/工作流库/面板自升级的下载器。

```
┌────────────────────── AutoDL 容器（Ubuntu, 无 systemd） ──────────────────────┐
│                                                                              │
│  浏览器（公网）                                                              │
│    │ HTTPS（AutoDL 端口映射 6006）                                           │
│    ▼                                                                        │
│  ┌────────────────────────── LaunchPad 后端 (FastAPI) ───────────────────┐   │
│  │  静态页面(Vue3 构建产物) + REST API + SSE(日志/进度)                  │   │
│  │                                                                       │   │
│  │  ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌─────────┐ ┌──────────────┐  │   │
│  │  │进程监督 │ │版本管理器│ │插件管理器│ │工作流   │ │系统状态采集  │  │   │
│  │  └────┬────┘ └────┬─────┘ └────┬─────┘ │管理器   │ └──────┬───────┘  │   │
│  │       │           │            │       └────┬────┘        │          │   │
│  └───────┼───────────┼────────────┼────────────┼─────────────┼──────────┘   │
│          ▼           ▼            ▼            ▼             ▼              │
│   python current/  versions/    custom_nodes/  workflows/   nvidia-smi 等    │
│   (ComfyUI 子进程) (符号链接)   (当前版本内)  (共享目录)                     │
│                                                                              │
│  /root/launchpad/        ← 面板自身（自升级替换区）                          │
│  /root/autodl-tmp/launchpad-data/  ← 全部大文件与用户数据（数据盘）          │
└──────────────────────────────────────────────────────────────────────────────┘
             │ 下载（学术加速可开）                    ▲ 首次安装
             ▼                                       │
   GitHub Releases（版本包 / 工作流库 / 面板发行包 / index.json）
```

**边界**：面板不代理 ComfyUI 的生成流量——「打开 ComfyUI」直接跳转 8188 端口映射域名；面板不触碰模型文件内容，只管理目录布局。

## 2. 模块

### backend/app/main — 应用壳
职责：FastAPI 装配、路由注册、静态文件挂载、SSE 通道、鉴权中间件、启动时状态对账（FR-002）。
依赖：全部子模块。拥有：HTTP 边界、令牌校验。

### backend/app/process — 进程监督器
职责：ComfyUI 子进程生命周期（start/stop/restart）、进程组管理、stdout/stderr 采集进环形缓冲与日志文件、退出码记录、面板重启后的孤儿进程对账。**领域核心，不依赖 FastAPI**。
依赖：config、logging。拥有：ProcessState 状态机的全部迁移。

### backend/app/versions — 版本管理器
职责：拉取/缓存版本索引、下载版本包（SHA-256 校验、原子解压）、`current` 符号链接切换、删除版本、共享数据布局建立（FR-006/007）。
依赖：downloader、config。拥有：versions/ 目录与 current 链接。

### backend/app/plugins — 插件管理器
职责：扫描 custom_nodes、读插件元数据、git pull 更新、启用/禁用（目录后缀法）。
依赖：downloader（可选加速）。拥有：custom_nodes 的写操作。

### backend/app/workflows — 工作流管理器
职责：拉取/缓存官方库索引、导入（复制+登记）、本地上传校验入库、删除、依赖清单解析（扫 JSON 里的模型文件名并对本机 models 匹配）。
依赖：downloader、config。拥有：共享工作流目录与登记表。

### backend/app/sysinfo — 系统状态采集器
职责：nvidia-smi / /proc/meminfo+cgroup / df / python 版本 / CUDA 探测，统一输出 SysStatus 快照；单源失败不影响其他源。
依赖：无（只读系统）。拥有：状态缓存（供轮询）。

### backend/app/downloader — 下载器
职责：统一 HTTP 下载（进度回调、断点提示、SHA-256 校验、临时目录原子落盘）、学术加速代理环境的装配与降级。
依赖：config（加速开关、渠道 URL）。拥有：网络下载细节；**渠道 URL 可配置，是提供方边界**。

### backend/app/selfupdate — 自升级器
职责：检查面板新版本、下载发行包、新目录解压、切换 launchpad 符号链接、经外部 supervisor 脚本自重启、健康检查失败回滚。
依赖：downloader。拥有：/root/launchpad/ 目录与 current 链接。

### backend/app/config — 配置与持久化
职责：面板设置（令牌哈希、端口、加速开关、启动参数、渠道 URL、主题）JSON 文件读写（原子写+备份），路径常量集中定义。
依赖：无。拥有：config.json schema。

### frontend/ — Vue 3 SPA
职责：全部呈现与交互；不包含任何业务规则（如"运行中禁止切换"的判定由后端 API 权威返回，前端只做展示层禁用）。
依赖：后端 API 契约（docs/API_SPEC.md）。拥有：视图状态。

### scripts/ — 安装/卸载/supervisor
职责：install.sh / uninstall.sh / launchpad 管理命令 / supervisor.sh（自升级接管与 bashrc 自启拉起）。
依赖：无。拥有：/root/launchpad 目录布局与 bashrc 注入片段。

## 3. 数据流

**启动 ComfyUI**：前端 POST /api/comfy/start → 鉴权 → 进程监督器读启动配置 → （加速开关开则装配代理环境）spawn `python main.py` 进程组 → 逐行采集日志 → 状态 starting → 探测 8188 端口就绪 → running；SSE 推送日志与状态。

**安装版本**：GET /api/versions（索引，带缓存）→ POST /api/versions/{v}/install → 下载器下载到临时目录（进度 SSE）→ SHA-256 校验 → 解压 → 建共享布局符号链接 → rename 正式目录 → （可选自动）切换 current → 完成事件。

**自升级**：POST /api/self/update → 下载新发行包到新目录 → 写切换指令给 supervisor.sh → 面板响应"升级中"→ supervisor 停旧面板 → 切链接 → 起新面板 → 健康检查（失败回滚旧目录并重启）。

**导入工作流**：POST /api/workflows/import {source: official|upload, id/file} → 校验 JSON → 解析依赖模型清单 → 复制到共享工作流目录 → 更新登记表 → 返回依赖对比结果。

## 4. 外部服务

| 服务 | 用途 | 适配器 | 备注 |
|---|---|---|---|
| GitHub Releases（本项目仓库） | 面板发行包、ComfyUI 版本包、index.json | downloader 的 channel 配置 | URL 可配置，二期可换镜像源/共享目录 |
| 工作流库 Releases（独立渠道） | workflows/index.json + 工作流文件 | 同上，独立 channel | 作者发库不发面板（FR-009） |
| AutoDL 学术加速（/etc/network_turbo） | 加速 GitHub 等下载 | downloader 的 proxy env 装配 | 不存在/超时降级直连 |
| nvidia-smi / procfs / df | 系统状态 | sysinfo 采集器 | 只读，单源失败隔离 |
| 本机 ComfyUI HTTP（127.0.0.1:8188） | 就绪探测（GET /system_stats） | 进程监督器内轻量探测 | 不深度依赖其 API |

## 5. 架构不变量

1. **数据盘原则**：一切可重建之外的数据（版本、共享模型/输出/工作流、配置备份）只写 `/root/autodl-tmp/launchpad-data/`；`/root/launchpad/` 仅放面板自身（可随时重装重建）。
2. **原子写**：所有目录/文件变更（版本安装、自升级、配置保存）先写临时路径再原子 rename；半成品绝不进入正式路径。
3. **单一权威状态**：ComfyUI 进程状态只由进程监督器定义；API 返回的即是权威，前端不得自行推断。
4. **令牌强制**：除 `/api/health`（供自升级健康检查，仅本机回环可访问）外无匿名端点。
5. **业务规则不进前端**：禁止切换/删除等守卫全部在后端强制，前端禁用仅为体验。
6. **提供方隔离**：渠道 URL、加速机制只存在于 config 与 downloader；换源不改业务模块。
7. **不删用户数据**：卸载、版本删除、工作流删除的路径白名单硬编码校验，防目录穿越与误删。

## 6. 技术决策

| 决策 | 选择 | 原因 |
|---|---|---|
| 后端框架 | FastAPI + uvicorn（单 worker） | 异步 SSE 友好、Pydantic 校验、AutoDL 自带 Python |
| 前端 | Vue 3 + Vite + Pinia + Vue Router | 生态成熟、构建产物纯静态由后端挂载 |
| 日志推送 | SSE（非 WebSocket） | 单向推送够用、代理/映射端口兼容性最好 |
| 进程管理 | asyncio 子进程 + 进程组 | 容器无 systemd；supervisor 只负责面板自身拉起 |
| 持久化 | JSON 文件（原子写）+ SQLite（工作流登记表，若规模超千条再引入） | 无 DB 服务依赖；`[AI-DECIDED]` MVP 直接用 JSON 登记表，SQLite 仅在列表性能成问题时引入 |
| 版本包格式 | tar.zst 自包含（源码+venv，torch 引镜像环境） | 解压快、体积可控 |
| 打包 CI | GitHub Actions → Releases | 与下载渠道同栈 |
| 面板自启 | bashrc 注入片段 + supervisor.sh | AutoDL 容器无 systemd（已核实：弹性部署启动命令/bachrc 是仅有的两种方式） |
| 内部 HTTP | uvicorn 绑 127.0.0.1:<panel_port>，AutoDL 映射对外 | 不直接暴露 |

## 7. 显式非目标

- 不做生成功能、不做多用户、不做 AutoDL API 集成、不做 Windows（见 PROJECT_BRIEF 范围外）。
- 不代理/改造 ComfyUI 前端，不修改 ComfyUI 源码（只外挂目录布局与启动方式）。
- 面板不承担模型下载（用户用 ComfyUI-Manager 或公共模型库）。

## 8. 架构变更政策

上述模块边界、不变量、提供方边界的变更属于重大架构变更：必须先在本文件提 PR 说明冲突、原因、备选与迁移成本，经用户批准后才可实施。模块内部实现方式可自由演进。
