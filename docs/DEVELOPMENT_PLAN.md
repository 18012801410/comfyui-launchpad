# 开发计划（Development Plan）

> 任务文件保存为 `docs/tasks/TASK-XXX.md`；每个任务进入实现前才落成完整 TASK 文件（后续任务按前序任务的学习成果细化，避免过早僵化）。下表为全部任务的权威清单。

## 阶段 0 — 产品
状态：DONE（docs/PROJECT_BRIEF.md 已批准）

## 阶段 1 — 架构与规格
状态：DONE（REQUIREMENTS / ARCHITECTURE / DOMAIN_MODEL / TECH_SPEC / API_SPEC / UI_SPEC / DESIGN_SYSTEM / AI_SPEC / AI_RULES）

## 阶段 2 — 仓库基线与应用壳
状态：NOT_STARTED
- TASK-001 仓库脚手架与工程基线（目录、工具链、CI 骨架）
- TASK-002 配置/路径白名单/令牌安全核心 + 单测
- TASK-003 应用壳：/api/health、鉴权中间件、auth 路由 + 测试

## 阶段 3 — 领域核心（进程/状态）
状态：NOT_STARTED
- TASK-004 进程监督器领域模块（ProcessState 状态机、环形日志、重启对账）+ 单测
- TASK-005 sysinfo 采集器（GPU/内存/磁盘/CUDA，单源失败隔离）+ 单测

## 阶段 4 — API 层与实时通道
状态：NOT_STARTED
- TASK-006 ComfyUI 控制路由 + SSE 事件总线 + LaunchConfig 路由 + 测试

## 阶段 5 — 版本系统（最大风险块）
状态：NOT_STARTED
- TASK-007 下载器（进度/SHA-256/原子落盘/学术加速装配与降级）+ 单测
- TASK-008 版本管理器与渠道索引 schema（install/switch/delete + 共享布局）+ 单测
- TASK-009 版本包构建流水线（packaging 脚本 + GitHub Actions 矩阵 + index 发布；同时定稿 torch 兼容矩阵，关闭待定问题 #4）

## 阶段 6 — 插件与工作流
状态：NOT_STARTED
- TASK-010 插件管理器 + 路由 + 测试
- TASK-011 工作流管理器（官方库渠道/上传校验/依赖解析）+ 路由 + 测试

## 阶段 7 — 分发与自升级
状态：NOT_STARTED
- TASK-012 安装/卸载/launchpad 管理脚本 + supervisor + bashrc 自启
- TASK-013 自升级器 + 面板发行打包 + release-panel workflow

## 阶段 8 — 前端全量
状态：NOT_STARTED
- TASK-014 前端基座（Vite/Vue3/TS/Naive UI、AppShell、TokenGate、主题、API client、SSE store）
- TASK-015 启动台页面（ActionBar/状态卡/LogConsole/启动参数抽屉）
- TASK-016 版本管理页
- TASK-017 插件管理页
- TASK-018 工作流管理页
- TASK-019 系统设置页（令牌/自升级/面板日志/自检）

## 阶段 9 — 端到端验证与发布
状态：NOT_STARTED
- TASK-020 真实 AutoDL 实例端到端冒烟 + 安装自检 + 发布准备（RELEASE_CHECK）

> 说明：后端先行、前端后置——阶段 8 之前全部 API 可用 curl/pytest 验证，前端一次性对接稳定契约，避免联调反复。任务排序即依赖序：001→002→003→(004,005)→006→(007→008→009)→(010,011)→(012,013)→(014→015…019)→020。

## 当前里程碑
M1「可启动」：TASK-001~006（面板能启停本机已有 ComfyUI 并看状态日志）
M2「可分发」：TASK-007~013（版本系统 + 安装脚本 + 自升级）
M3「可发布」：TASK-014~020（全 UI + 真实环境验证 + 公开发布）

## 下一步任务
1. TASK-001 仓库脚手架与工程基线
2. TASK-002 配置/路径/令牌核心
3. TASK-003 应用壳与鉴权
