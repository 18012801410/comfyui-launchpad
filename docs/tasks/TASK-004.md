# 任务 TASK-004

保存为 `docs/tasks/TASK-004.md`。

## 目标
进程监督器领域模块：ProcessState 五态状态机、子进程组管理、环形日志缓冲、退出码记录、面板重启后对账，纯领域层可测。

## 背景
启动器的核心价值（FR-002）；状态机与不变量在 DOMAIN_MODEL 已定义，是全项目最不能出错的模块。

## 参考
- docs/DOMAIN_MODEL.md（ComfyProcess：状态、迁移、不变量、副作用）
- docs/ARCHITECTURE.md（模块：process；不变量 3 单一权威状态）
- docs/AI_RULES.md（领域层禁 import fastapi/httpx）

## 范围
- `domain/process_supervisor.py`：asyncio.subprocess spawn（进程组、参数数组、无 shell）、SIGTERM→10s→SIGKILL 停止序列、stdout/stderr 逐行采集、就绪探测（GET 127.0.0.1:port/system_stats，超时上限可配）、事件发布（ProcessStateChanged/LogAppended 走 core 事件总线接口）
- 状态机守卫：非法迁移抛 InvalidTransition（含 running→starting 直接跳转）
- 对账：`reconcile()`——按记录的 pid 文件检查遗留进程，running 则纳入监控、僵死则清理并标 failed→stopped
- LaunchConfig 快照注入（config 来自 TASK-002 模型，含 extra_args 白名单校验入口）
- 单测：用 fake 脚本（sleep/echo 的 python 小进程）驱动全部合法迁移；非法迁移拒绝；SIGKILL 升级路径（mock 信号）；对账三场景（无遗留/存活/僵死）
- 接口留出：事件总线用 Protocol 定义（TASK-006 接 SSE）

## 非目标
- API 路由（TASK-006）
- 学术加速环境装配（TASK-007 downloader 一并实现，本任务接口接收 env 参数即可）
- 真实 ComfyUI 启动联调（TASK-020）

## 需求
1. 全部测试不依赖真实 GPU/ComfyUI
2. 进程句柄无泄漏（测试后无孤儿进程）

## 验收标准
- [ ] 状态机全部合法/非法迁移有用例覆盖
- [ ] 停止序列在 fake 进程上实测 SIGTERM 生效与 SIGKILL 升级两条路径
- [ ] 日志环形缓冲 2000 行上限且逐行时间戳正确

## 验证
- [ ] ruff + mypy + pytest（含 no orphan 断言）
- [ ] 手动：对 sleep 进程 start/stop 一次，观察事件序列

## 预期报告
- 变更文件 / 实现摘要 / 验证结果 / 遗留问题 / 架构影响（无）
