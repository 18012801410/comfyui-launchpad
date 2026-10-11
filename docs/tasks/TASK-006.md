# 任务 TASK-006

保存为 `docs/tasks/TASK-006.md`。

## 目标
API 层成型：ComfyUI 控制路由（API-004~007）、系统状态路由（API-008）、SSE 事件总线（API-020），M1 里程碑达成（curl 可完整启停+看日志+看状态）。

## 背景
后端先行策略的第一个集成交付点：此前各领域模块经此任务首次对外，契约以 API_SPEC 为权威。

## 参考
- docs/API_SPEC.md（API-004~008、API-020、错误码）
- docs/DOMAIN_MODEL.md（命令映射）
- TASK-003/004/005 产物

## 范围
- 路由：/api/comfy/status|start|stop|restart|logs、/api/comfy/launch-config（GET/PUT）、/api/system/status
- 领域事件总线 → SSE 转发（topics 订阅过滤、15s 心跳、断连清理）；LogAppended/ProcessStateChanged/DownloadProgress 三类事件先通（后两类占位源）
- launch-config PUT：preset 展开（default/low_vram/fp16_fast 参数表）、extra_args 白名单校验、保存原子写、warnings 回显
- start 守卫链：版本未装 → version_not_installed；进程非 stopped → conflict_process_running；端口被占 → port_conflict；参数非法 → invalid_launch_args
- 测试：TestClient 全端点 + SSE（httpx 流式读取首事件与心跳）；守卫链每分支一例

## 非目标
- 前端任何部分
- 版本安装 API（TASK-008；本任务用「当前未装版本」桩状态使 start 守卫可测）

## 需求
1. 路由层零业务规则（全部委托领域模块）
2. SSE 断开不泄漏生成器/队列

## 验收标准
- [ ] API-004~008、020 请求响应样逐字段一致
- [ ] 用 fake ComfyUI 脚本（TASK-004 遗留）走通 start→logs→status→stop 全流程（pytest 集成用例）
- [ ] 并发两次 start 恰好一成一败（conflict_process_running）

## 验证
- [ ] ruff + mypy + pytest
- [ ] 手动：uvicorn 启动，curl 脚本走通 M1 验收（本机无 GPU 时状态卡降级显示）

## 预期报告
- 变更文件 / 实现摘要 / 验证结果 / 遗留问题 / 架构影响（无）
- 附：M1 里程碑达成声明（若全绿）
