# 领域模型（Domain Model）

> 核心原则：领域逻辑（进程状态机、版本生命周期、守卫规则）独立于 FastAPI 与 Vue，纯 Python 可测试。

## 核心实体

### 实体：ComfyProcess（ComfyUI 进程执行）

用途：当前版本 ComfyUI 的运行执行体，是「执行（Execution）」概念。
标识：单例（同一时刻至多一个）；以 `pid + started_at` 区分历史次。
归属：process 模块。

字段：
- state: ProcessState
- pid: int | None
- started_at / stopped_at: datetime | None
- exit_code: int | None
- last_heartbeat: datetime（就绪探测结果）
- launch_snapshot: LaunchConfig（本次启动实际用的参数副本）

状态（ProcessState）：
- `stopped` 未运行
- `starting` 已 spawn、未就绪
- `running` 8188 就绪探测通过
- `stopping` 正在优雅终止
- `failed` 异常退出（exit_code ≠ 0 / spawn 失败）

合法迁移：
- stopped → starting（用户启动）
- starting → running（就绪探测通过）
- starting → failed（进程退出且非用户停止）
- running → stopping（用户停止/重启第一段）
- running → failed（进程崩溃）
- stopping → stopped（SIGTERM 生效或升级 SIGKILL 后）
- failed → stopped（用户确认/下次启动前自动清位）
- running/failed → starting（restart = stop + start 组合，经由 stopping）

非法迁移：running → starting 直接跳转（必须经 stopping）；stopped → running（必须经 starting，由就绪探测判定）。

迁移副作用：进入 starting 时快照启动配置；进入 stopped/failed 时记录退出码并刷新 sysinfo 进程卡。
重试/取消：starting 阶段可取消（等价停止）；不对启动失败自动重试（避免风暴），只报告。

不变量：
- 同一时刻至多一个非 stopped 状态实例。
- 非 stopped 状态下禁止版本切换/删除、插件对运行中文件的操作。
- state 只能由 process 模块内部迁移，外部只能发命令。

版本化：无（执行记录仅保留最近 N 次摘要供日志页）。

### 实体：ComfyVersion（ComfyUI 版本）

用途：一个可安装/已安装的 ComfyUI 版本；区分「定义（Definition，索引里的一条）」与「实例（已解压落盘的目录）」。
标识：`version` 字符串（语义化版本，如 `0.39.0`）。
归属：versions 模块。

字段（定义，来自 index.json）：
- version, release_date, torch_baseline, min_python, size_mb, sha256, url, notes, deprecated: bool

字段（实例，落盘后）：
- installed_at, last_used_at, disk_size_mb, status: `installing` | `ready` | `broken`

状态：`installing`（临时目录中）→ `ready`（rename 完成）→ `broken`（校验/启动自检失败，可删除重装）。

合法迁移：
- （未安装）→ installing（下载开始）
- installing → ready（原子 rename 成功）
- installing → （未安装）（下载/校验失败，清理临时目录）
- ready → broken（结构校验失败）

不变量：
- `current` 符号链接当且仅当指向一个 ready 实例；无任何 ready 实例时链接不存在（面板页显示「未安装版本」引导）。
- 任何时刻至多一个 installing 任务（下载队列串行）。
- ComfyProcess 非 stopped 时禁止 `current` 切换与任何实例删除。
- 每个实例的 models/output/input/user 必须是指向共享目录的符号链接（安装器建立，删除版本只删实例目录本身）。

版本化：实例目录即版本化本体（`versions/<ver>/`），删除即失去该版本（可重新下载）。

### 实体：LaunchConfig（启动配置）

用途：ComfyUI 的启动参数「配置（Configuration）」，与执行分离。
标识：单例（当前生效配置）+ 启动时快照。
归属：config 模块。

字段：
- listen_port: int = 8188
- extra_args: str（用户自由追加，白名单字符校验）
- preset: `default` | `low_vram` | `fp16_fast` | `custom`
- academic_accel: bool
- auto_open_hint: bool

不变量：
- listen_port ∈ [1024, 65535] 且 ≠ 面板端口。
- extra_args 经字符白名单与长度限制校验（防注入）。
- 修改只写配置文件，生效须下一次启动（快照保证可复现）。

版本化：配置文件保留上一份备份（原子写+backup）。

### 实体：Plugin（插件）

用途：当前版本 custom_nodes 下的一个插件实例。
标识：目录名。
归属：plugins 模块。

字段：
- name, dir_name, enabled: bool（目录是否带 `.disabled` 后缀）
- summary, version_hint（pyproject/README 摘要）
- git_url, git_ref, update_status: `up_to_date` | `behind` | `unknown` | `dirty`
- has_remote: bool

状态（更新生命周期）：`unknown`（无 git 元数据/本地安装）→ `behind`（fetch 后落后）→ `up_to_date`。

合法迁移：enabled ↔ disabled（目录改名）；update_status 按上述。

不变量：
- 插件写操作（update/enable/disable）在 ComfyProcess 非 stopped 时允许（插件不与进程抢文件锁），但 UI 提示需重启生效；update 失败必须保证目录仍可用（失败即回滚到更新前 ref）。
- 禁止操作 shared 目录与版本目录外的任何路径。

版本化：git 本身即版本化；不做额外快照。

### 实体：WorkflowItem（工作流条目）

用途：一条已入库（导入/上传）的工作流；区分「库定义（官方索引条目）」与「本地实例（已导入/上传的文件）」。
标识：本地 `workflow_id`（uuid）；库定义以 `library_slug` 幂等对应。
归属：workflows 模块。

字段（本地实例）：
- workflow_id, name, source: `official` | `upload`
- library_slug | None（官方来源的幂等键）
- library_version | None（导入时库索引版本，便于提示更新）
- file_path（共享工作流目录内）
- imported_at, preview_url | None
- dependency_report: [{model_file, category, present: bool, suggest_dir}]

字段（库定义，来自 workflows/index.json）：
- slug, name, category, description, preview_url, models_required[], updated_at, file_url, sha256

不变量：
- 本地文件只存在于共享工作流目录白名单内。
- 上传 JSON 必须通过 ComfyUI 工作流格式校验（含 `nodes` 数组或 API 格式 `prompt` 键，二者之一）方可入库。
- 删除本地条目不删除库定义；同 slug 重复导入 = 覆盖更新（保留 workflow_id）。

版本化：导入/上传覆盖前自动把旧文件移入 `workflows/.history/<id>/<timestamp>.json`（保留最近 5 份）。

### 实体：PanelRelease（面板发行版）

用途：面板自身的可升级「定义」；安装本体是 `/root/launchpad/current` 指向的目录（实例）。
标识：`panel_version`（如 `2026.10.10`）。
归属：selfupdate 模块。

字段：version, release_notes, sha256, url, published_at, min_upgrade_from（低于该版本须先两步升级，预留）。

状态（升级执行）：`idle` → `downloading` → `staging`（新目录就绪）→ `switching`（supervisor 接管）→ `idle`（新版本就绪）｜`rolled_back`。

不变量：
- `/root/launchpad/` 始终保留上一成功版本目录（`releases/<v>/` + current 链接），至多保留最近 2 个。
- 升级任何阶段失败都回到上一 ready 目录；config.json 与令牌跨版本保留（位于数据盘）。
- 健康检查（/api/health，仅回环）连续失败 3 次判定失败。

### 实体：PanelSettings（面板设置）

用途：面板级配置（Configuration）。
标识：单例文件 config.json。
归属：config 模块。

字段：token_hash（SHA-256+盐）、panel_port、channels.{versions,workflows,self}（渠道 URL）、academic_accel_default、theme、autostart_enabled、first_installed_at。

不变量：令牌只存哈希；文件原子写 + `.bak` 备份；面板重启不丢。

## 定义与实例

- ComfyVersion：index.json 条目 = 定义；versions/<ver>/ 目录 = 实例。
- WorkflowItem：库索引条目 = 定义；本地导入文件 + 登记记录 = 实例。
- PanelRelease：Release 元数据 = 定义；releases/<v>/ = 实例。
- LaunchConfig：当前配置文件 = 配置；启动快照 = 执行引用的精确版本。

## 命令

- StartComfy(config_snapshot) / StopComfy / RestartComfy
- InstallVersion(v) / SwitchVersion(v) / DeleteVersion(v) / RefreshVersionIndex
- UpdatePlugin(name) / EnablePlugin(name) / DisablePlugin(name)
- ImportOfficialWorkflow(slug) / UploadWorkflow(file) / DeleteWorkflow(id) / RefreshWorkflowIndex
- CheckPanelUpdate / PerformSelfUpdate / RegenerateToken
- SetLaunchConfig / SetAcademicAccel(bool)

所有命令经 API 层校验后调用领域模块；命令结果统一为 `{ok, state_after, error?}`。

## 事件

- ProcessStateChanged(state, pid?, exit_code?)
- LogAppended(source: comfy|panel, line)
- DownloadProgress(task_id, kind: version|panel|workflow, received, total)
- VersionInstalled(v) / VersionSwitched(v) / VersionRemoved(v)
- WorkflowImported(item) / PanelUpgraded(v) / PanelRollback(from)

实现：进程内事件总线；SSE 通道订阅转发。

## 资产/结果

- 版本实例目录、共享模型/输出/工作流文件、面板日志文件——均落在数据盘白名单路径。

## 序列化

- config.json / workflows-registry.json / versions-state.json（各版本 installed_at 等）持久化于 `/root/autodl-tmp/launchpad-data/state/`（原子写）。
- API 载荷见 docs/API_SPEC.md；ProcessState 与下载进度经 SSE 文本事件传输。
