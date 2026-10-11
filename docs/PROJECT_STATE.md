# 项目状态（Project State）

> 每个有意义的里程碑后更新本文件。新会话从这里恢复上下文。

## 当前阶段
阶段 2-4 DONE —— **M1「可启动」达成**（TASK-001~006 全绿 + curl 冒烟通过）。进入 M2「可分发」（TASK-007 起）。

## 当前任务
无进行中任务。下一个：TASK-007（下载器）。

## 已完成
- TASK-001~006：脚手架、core 三件套、鉴权应用壳、进程监督器（五态状态机/对账/环形日志）、sysinfo 采集器、ComfyUI 控制路由+SSE+LaunchConfig
- 后端 54 项测试全绿（ruff/mypy/pytest）
- M1 curl 冒烟通过：鉴权、launch-config 预设、无版本启动 404、真实 GPU 检测（开发机 RTX 4060）、SSE 流、幂等 stop
- 关键实现事实：领域层纯净（无 fastapi/httpx）；就绪探测用 TCP（socket 标准库）；Windows 用 junction 兜底目录链接；run_cmd 显式 UTF-8+replace 解码；SSE 测试必须走真实 uvicorn 端口（httpx ASGITransport 不支持流式，且本机系统代理需 trust_env=False）
- 已核实事实：AutoDL 容器无 systemd（自启=弹性部署启动命令或 bashrc 注入）；学术加速=source /etc/network_turbo；6006 端口为文档保证的公网映射端口；参考面板（ZEALMAN Control Panel 3.0）功能形态已用浏览器勘察

## 当前架构决策
见 docs/ARCHITECTURE.md 第 6 节与 docs/PROJECT_BRIEF.md 决策表。要点：FastAPI+Vue3；CI 打包自包含 ComfyUI 版本包经 GitHub Releases 分发；current 符号链接秒切；数据全部落 autodl-tmp 数据盘；SSE 推日志；令牌强制鉴权；面板 6006、ComfyUI 8188。

## 当前领域决策
- ProcessState 状态机五态（stopped/starting/running/stopping/failed），迁移合法性见 DOMAIN_MODEL。
- ComfyVersion 定义（索引条目）与实例（versions/<ver>/ 目录）分离；不变量「current 必指向 ready 实例」。
- 工作流库与面板解耦（独立 Release 渠道），作者发库不发面板。

## 已知问题
- 无代码，尚无实现问题。

## 待定问题（Open Questions）
1. 是否开源（发布前定，不阻塞开发）
2. 版本包双发 AutoDL 共享目录（二期评估）
3. 工作流库首批内容（TASK-011 前由作者提供；schema 已在 API_SPEC/API-013 定义）
4. torch 兼容矩阵（TASK-009 定稿）
5. Naive UI 组件库选型标为 [AI-DECIDED]（DESIGN_SYSTEM），用户可否决

## 阻塞项
- 无

## 近期变更
- 2026-10-11：建立规格说明包（本次会话）。

## 下一个任务
TASK-007 下载器（infra/downloader：进度回调/SHA-256/原子落盘/学术加速装配）。

## 智能体交接备注
- 后端测试命令：cd backend && ruff check . && mypy app && pytest（全绿才算完成）。
- SSE/流式相关测试不要用 httpx ASGITransport（会挂死），用真实 uvicorn 端口 + trust_env=False（本机有系统代理）。
- Windows 开发机有真实 NVIDIA GPU（nvidia-smi 可用）；Git Bash 的 /tmp 与 Python 路径不一致，集成冒烟用 C:/ 前缀路径。
- 领域层纯净性（不 import fastapi/httpx）与四大风险（进程安全/路径白名单/原子写/令牌脱敏）见 AI_RULES。
- 面向用户的错误信息与 UI 全部中文。
