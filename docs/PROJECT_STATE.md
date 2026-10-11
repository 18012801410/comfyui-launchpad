# 项目状态（Project State）

> 每个有意义的里程碑后更新本文件。新会话从这里恢复上下文。

## 当前阶段
阶段 1 — 架构与规格：DONE。等待进入 阶段 2（仓库基线）。

## 当前任务
无进行中任务。下一个：TASK-001。

## 已完成
- 头脑风暴与 docs/PROJECT_BRIEF.md（用户批准，含 12 条决策记录）
- 规格说明包：REQUIREMENTS / ARCHITECTURE / DOMAIN_MODEL / TECH_SPEC / API_SPEC / UI_SPEC / DESIGN_SYSTEM / AI_SPEC / AI_RULES / DEVELOPMENT_PLAN
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
TASK-001 仓库脚手架与工程基线（docs/tasks/TASK-001.md）。

## 智能体交接备注
- 本仓库当前只有 docs/ 与 .agents/，无任何代码；从 TASK-001 开始搭脚手架。
- 领域层纯净性（不 import fastapi/httpx）与四大风险（进程安全/路径白名单/原子写/令牌脱敏）见 AI_RULES。
- 面向用户的错误信息与 UI 全部中文。
- 开发在 Windows，目标环境 Linux（AutoDL）——路径相关逻辑集中 core/paths.py 并优先在 WSL/CI 验证。
