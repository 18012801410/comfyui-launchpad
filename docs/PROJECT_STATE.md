# 项目状态（Project State）

> 每个有意义的里程碑后更新本文件。新会话从这里恢复上下文。

## 当前阶段
**M1/M2/M3 本地开发全部完成**（TASK-001~020 全部关闭，除「真实 AutoDL 实例冒烟」待用户提供实例后执行）。

## 当前任务
无进行中任务。项目处于「待发布准备」状态——剩余事项均为需要用户资源的外部依赖（见阻塞项）。

## 已完成（2026-10-11 单日完成全部 20 个任务）
- **M1 可启动**：脚手架 / core 三件套 / 鉴权应用壳 / 进程监督器（五态状态机）/ sysinfo / ComfyUI 控制路由+SSE
- **M2 可分发**：下载器 / 版本管理器（索引+安装+切换+删除+共享布局）/ 版本包构建流水线 / 插件管理器 / 工作流管理器（官方库+上传+依赖解析）/ 安装卸载脚本+自启 / 自升级器+面板打包发布流水线
- **M3 可发布**：前端全量（令牌门/AppShell/启动台/版本/插件/工作流/设置，亮暗主题）+ 本机端到端浏览器验证
- **验证状态**：后端 87 项测试全绿（ruff/mypy/pytest）；前端 vue-tsc+vite 构建全绿；5 个 shell 脚本 bash -n 通过；浏览器 E2E 实测通过（登录→启动→SSE 实时日志→运行中→停止，全页面巡检）

## 当前架构决策
见 docs/ARCHITECTURE.md 与 docs/PROJECT_BRIEF.md 决策表。E2E 阶段新增/修正的实现级事实：
- Naive UI 全局注册（main.ts `app.use(naive)`）
- SPA 回退用 SPAStaticFiles 子类（404 且非 api/ → index.html；须捕获 Starlette HTTPException）
- 自升级契约：updater 传 staging 目录给 supervisor switch，supervisor 落位 releases/→停旧→切 current→健康检查→失败回滚
- versions 目录扫描跳过 current 链接；python ABI 校验（entry.python_abi vs 实例 Python）

## 当前领域决策
- ProcessState 五态机、ComfyVersion 定义/实例分离、工作流库与面板解耦（详见 DOMAIN_MODEL.md）
- 插件按版本存放（custom_nodes 不跨版本共享，代码兼容优先）
- torch 不进版本包；python_abi 显式建模（docs/TORCH_COMPAT.md）

## 已知问题
- 无已知功能性缺陷。测试覆盖外的环境风险见「阻塞项」。

## 待定问题（Open Questions）
1. 是否开源（发布前定）——决定仓库可见性与安装命令里的 GitHub 地址
2. 官方工作流库首批内容（用户待提供；schema 见 channels/versions-index.json 同构的 workflows-index）
3. 版本包双发 AutoDL 共享目录（二期评估）

## 阻塞项（均为需要用户资源的外部依赖，非代码问题）
1. **GitHub 仓库与发布**：尚未配置 git remote；CI（ci.yml / build-versions.yml / release-panel.yml）与「一键安装命令」都依赖仓库就位。发布步骤：建 2~3 个仓库（panel/versions/workflows 或单仓库）→ push → 手动触发 release-panel.yml（版本号如 0.1.0）→ 把 channels 默认 URL 从 REPLACE_ME 改为实际仓库 → 打首个 ComfyUI 版本包（build-versions.yml）
2. **真实 AutoDL 实例冒烟**（TASK-020 收尾）：在一台真实实例上执行 install.sh 全流程（本机为 Windows，仅做了 bash -n 与 CLI 逻辑验证）
3. **官方工作流库首批工作流**（用户提供 JSON 后发首个库 Release）

## 近期变更
- 2026-10-11（夜）：**公网 WS 重连循环根因修复**——三连击：①实例 websockets≥14 的 connect 参数改名（extra_headers→additional_headers），按版本自适应传参；②网关代理改写 Origin/Referer 为后端视角（ComfyUI 防 DNS 重绑定校验曾导致浏览器经网关访问全部 403 = 白屏元凶）；③uvicorn 关闭 WS PING（AutoDL 网关不转发控制帧时 30s 循环断开的防御）。实测 35 秒观察窗口 403 零新增、页面无重连。另：ComfyUI 日志落盘已在真实故障中立功。镜像适配经验：此类镜像开机自启 ComfyUI 占 6006（start-comfyui.sh），面板接管方式=改写该脚本+补 /etc/autodl.sh 双钩子。
- 2026-10-11（深夜）：**鉴权网关提前落地**（原二期方案，被真机使用场景逼出）：面板域名下 `根路径` 反向代理 ComfyUI（HTTP 流式 + WebSocket 双向泵），面板自身收缩到 `/panel/*`（API=/panel/api、SPA=/panel）；「打开 ComfyUI」打开 `/` 即 ComfyUI 界面，公网直用。顺带修复重装双进程 bug（install.sh 端口探测前先停旧面板）。公网实测：/ → ComfyUI UI、/system_stats、/panel/、/panel/api/versions（令牌）全部通过。
- 2026-10-11（深夜）：**首次真实 AutoDL 实例部署成功**（用户实例 westd.seetacloud，ComfyUI 应用镜像）。关键经验：①这类镜像开机自启 ComfyUI 占 6006（经 /root/start-comfyui.sh，源自镜像）；②面板接管方式=改写该脚本+补 /etc/autodl.sh 双钩子拉起面板，原件备份 .orig；③公网映射只有 6006→8443 一条（环境变量 AutoDLService6006URL 可查），面板占 6006 后 ComfyUI UI 外部访问暂需 SSH 隧道（鉴权网关为二期正解）；④miniconda Python 无 python3 命令，部署需 PYTHON_BIN 显式指定；⑤deploy_autodl.sh 已就绪（密码登录场景暂需手动/paramiko，可后续加 sshpass 支持）
- 2026-10-11（晚）：方案A listen_host 对外暴露 + start/stopping 竞态修复 + README AutoDL 部署流程（install.sh 源码直装模式）
- 2026-10-11（晚）：**采纳对标实例的公共模型挂载方式**——版本安装时自动生成 extra_model_paths.yaml，三段映射：面板共享布局 + /root/autodl-tmp/models（数据盘）+ /root/autodl-fs/models（文件存储网盘，跨实例共享）；已有文件绝不覆盖；真机验证 ComfyUI 日志确认加载
- 2026-10-11：完成 TASK-012~020（脚本/自升级/前端全量/E2E），修复 E2E 揭出的 4 个问题（Naive UI 未注册、SPA 回退 404、versions 扫描含 current、/api/panel/logs 未实现）
- 2026-10-11：对标源码勘察结论（用户提供 D:\comfyui\ComfyUI，为实例 ComfyUI 目录而非面板本体）：①对标把 ComfyUI 本身跑在 6006 公网映射端口（面板占另一映射口）；②公共模型=extra_model_paths.yaml + autodl-fs 网盘 + 公共模型库软链（已采纳）；③面板进程自启机制不在源码内，维持 bashrc+镜像路线判断

## 下一个任务
等待用户：① 提供 GitHub 仓库 → 完成发布（改渠道 URL + push + 触发 CI）；② 提供真实 AutoDL 实例 → 执行 install.sh 冒烟；③ 提供首批工作流 JSON → 发工作流库首个版本。

## 智能体交接备注
- 后端测试：cd backend && ruff check . && mypy app && pytest（87 项，全绿才算完成）
- 前端构建：cd frontend && npm run build（含 vue-tsc）
- SSE/流式测试不要用 httpx ASGITransport（挂死），用真实 uvicorn 端口 + trust_env=False（本机有系统代理）；Windows 上跑 bash 子进程须显式定位 Git Bash（create_subprocess_exec("bash") 会命中 WSL bash）
- Git Bash 的 /tmp 与 Python 路径不一致，集成冒烟用 C:/ 前缀路径
- 领域层纯净性（不 import fastapi/httpx）与四大风险（进程安全/路径白名单/原子写/令牌脱敏）见 AI_RULES
- 面向用户的错误信息与 UI 全部中文
