# 任务 TASK-002

保存为 `docs/tasks/TASK-002.md`。

## 目标
实现 core 三件：配置持久化（原子写+备份）、路径白名单、令牌安全（哈希存储/校验），全带单测。

## 背景
这是全项目安全性不变量（ARCHITECTURE 不变量 1/2/4/7）的实现地基，被所有后续模块依赖。

## 参考
- docs/TECH_SPEC.md（目录布局、config.json 字段、安全节）
- docs/DOMAIN_MODEL.md（PanelSettings）
- docs/ARCHITECTURE.md（不变量）

## 范围
- `core/paths.py`：数据盘/面板目录常量（可用 `LAUNCHPAD_DATA_DIR` 覆盖）、`safe_resolve()` 白名单校验（拒绝越界/符号链接逃逸）
- `core/config.py`：PanelSettings 读写（Pydantic 模型、临时文件+rename 原子写、.bak 备份、损坏时自动回退备份）
- `core/security.py`：令牌生成（secrets.token_urlsafe(32)）、盐哈希存储（hashlib.scrypt 或 sha256+salt）、常量时间比较、日志脱敏过滤器
- 单测：原子写中断模拟（写入后 rename 前抛异常不留半文件）、备份回退、路径穿越攻击样例（../、绝对路径、symlink）全部被拒、令牌校验时序安全（mock）
- channels 默认 URL 常量（指向占位仓库，TASK-009/013 填真值）

## 非目标
- FastAPI 集成（TASK-003）
- config 路由（TASK-019 对应 API-017 放 TASK-006/019 实现）

## 需求
1. Linux 与 Windows 双平台单测通过（开发在 Windows，目标 Linux）
2. 所有写操作不使用 shell
3. mypy 严格模式通过

## 验收标准
- [ ] 上述单测全绿且覆盖列出全部攻击样例
- [ ] config.json 损坏 50% 时程序仍能启动（回退 .bak）
- [ ] 日志注入含令牌字符串的输出被替换为 `***`

## 验证
- [ ] ruff + mypy + pytest
- [ ] 手动：删除 config.json 中间字节，重启读取回退成功

## 预期报告
- 变更文件 / 实现摘要 / 验证结果 / 遗留问题 / 架构影响（无）
