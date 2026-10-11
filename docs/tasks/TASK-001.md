# 任务 TASK-001

保存为 `docs/tasks/TASK-001.md`。

## 目标
建立仓库脚手架与工程基线：目录结构、前后端工具链、测试框架、CI 骨架，全部可通过（绿）。

## 背景
规格说明包已完成（docs/），仓库尚无代码。本任务建立后续所有任务依赖的工程骨架，不实现任何业务功能。

## 参考
- docs/TECH_SPEC.md（仓库结构权威定义）
- docs/AI_RULES.md
- docs/PROJECT_STATE.md

## 范围
- 按 TECH_SPEC 建目录：backend/app/{core,domain,infra,api}、backend/tests、frontend、scripts、packaging、channels、.github/workflows
- 后端：pyproject（fastapi、uvicorn、pydantic、httpx、zstandard；dev: pytest、ruff、mypy）、`app.main` 可启动、`GET /api/health` 返回版本号、pytest+ruff+mypy 通过
- 前端：Vite + Vue3 + TS + Naive UI + Pinia + Router 初始化，`npm run build`/`type-check` 通过，空壳 App.vue
- CI：.github/workflows/ci.yml（后端 lint+test；前端 build+type-check），暂不含发布
- .gitignore、README.md（项目一句话 + 开发环境启动方式）
- git init 与首次提交

## 非目标
- 任何业务模块（鉴权、进程、版本……）
- Naive UI 主题定制（TASK-014）
- 真实发布流水线

## 验收标准
- [ ] 目录结构与 TECH_SPEC 完全一致
- [ ] `cd backend && ruff check . && mypy app && pytest` 全绿（含 health 冒烟测试）
- [ ] `cd frontend && npm run build && npm run type-check` 全绿
- [ ] CI 推送后全绿
- [ ] README 写明本地启动两条命令

## 验证
- [ ] 后端 lint/type/test
- [ ] 前端 build/type-check
- [ ] `uvicorn app.main:app` 启动后 curl /api/health 返回 200

## 预期报告
- 变更文件 / 实现摘要 / 验证结果 / 遗留问题 / 架构影响（无）
