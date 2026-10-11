# ComfyUI LaunchPad（ComfyUI 启动台）

运行在 AutoDL GPU 实例内的 ComfyUI 启动器控制面板：一键安装、网页启停 ComfyUI、多版本切换、插件更新、工作流导入、系统状态监控、面板自升级。

> 规格说明包见 [docs/](docs/)，项目状态见 [docs/PROJECT_STATE.md](docs/PROJECT_STATE.md)。

## 开发环境

```bash
# 后端（Python ≥3.10）
cd backend
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"        # Linux/macOS: .venv/bin/pip
.venv/Scripts/uvicorn app.main:app --port 6006

# 前端（Node ≥20）
cd frontend
npm install
npm run dev        # 开发服务器，/api 代理到 127.0.0.1:6006
npm run build      # 类型检查 + 构建到 dist/
```

## 工程约定

- 后端：`ruff check . && mypy app && pytest` 全绿才算完成
- 前端：`npm run build`（含 vue-tsc 类型检查）全绿才算完成
- 每任务一提交，提交信息 `TASK-XXX: <一句话目标>`
- 领域层（`app/domain/`）禁止 import fastapi/httpx
