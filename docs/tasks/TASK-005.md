# 任务 TASK-005

保存为 `docs/tasks/TASK-005.md`。

## 目标
sysinfo 采集器：GPU/内存/磁盘/CUDA/Python 版本快照，单源失败隔离，输出 API-008 契约结构。

## 背景
FR-005；前端状态卡的数据源。采集目标环境是 AutoDL 容器（nvidia-smi 存在、cgroup 内存限额），开发环境（Windows/WSL）允许降级。

## 参考
- docs/API_SPEC.md（API-008 响应结构——权威契约）
- docs/TECH_SPEC.md（infra/shell 封装）
- docs/REQUIREMENTS.md（FR-005 验收：与人工命令核对一致、单源失败不连坐）

## 范围
- `domain/sysinfo.py` + `infra/shell.py`（参数数组调用 nvidia-smi --query-gpu/…，解析输出；/proc/meminfo + cgroup v2 limit；df -k 解析；python_version）
- 每源独立 try，失败源置 available:false + error
- 结果快照缓存（TTL 2s）避免轮询打爆
- 单测：以样例文本（真实 AutoDL 输出样例 + 异常输出）驱动解析器；不做真机断言
- Windows/无 GPU 环境：available:false 优雅降级

## 非目标
- API 路由（TASK-006）
- 历史曲线/图表

## 验收标准
- [ ] 样例解析输出与 API-008 字段一一对应
- [ ] 任一采集器抛异常时其余字段正常返回
- [ ] TTL 缓存生效（连续两次调用只执行一次底层命令）

## 验证
- [ ] ruff + mypy + pytest
- [ ] WSL 中手动运行快照打印

## 预期报告
- 变更文件 / 实现摘要 / 验证结果 / 遗留问题 / 架构影响（无）
