# 任务 TASK-003

保存为 `docs/tasks/TASK-003.md`。

## 目标
应用壳完成：鉴权中间件覆盖全部 API（除 /api/health 仅回环）、/api/auth/verify 与 /api/auth/rotate 落地、错误包络统一。

## 背景
令牌强制是安全不变量；统一错误包络是前后端契约地基（API_SPEC「原则」节）。

## 参考
- docs/API_SPEC.md（API-001/002/003、稳定错误码、包络）
- docs/ARCHITECTURE.md（不变量 4）
- TASK-002 的 core/security

## 范围
- FastAPI 中间件/依赖：无令牌或错令牌 → 401 `auth_required`；/api/health 仅 127.0.0.1
- auth 路由三端点（verify/rotate；rotate 后旧令牌立即失效）
- 统一包络与异常处理器（业务异常 → 稳定错误码；未知异常 → `internal` + 日志、不泄露堆栈）
- 测试：TestClient 覆盖全部端点的 401/200/错误分支、rotate 后旧令牌 401、/api/health 外部 IP 拒绝

## 非目标
- 前端 TokenGate（TASK-014）
- 其余业务路由

## 验收标准
- [ ] API_SPEC API-001/002/003 的请求响样逐字段一致
- [ ] 除 health 外任何路由无令牌均 401（用一个假路由验证中间件全局性）
- [ ] 令牌不出现在任何测试可观测的响应/日志中

## 验证
- [ ] ruff + mypy + pytest
- [ ] 手动 curl 三个端点

## 预期报告
- 变更文件 / 实现摘要 / 验证结果 / 遗留问题 / 架构影响（无）
