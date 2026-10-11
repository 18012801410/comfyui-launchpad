# API/契约规格（API / Contract Specification）

## 原则
- 契约是显式的：所有载荷 Pydantic 模型定义，本文为权威快照。
- 输入输出有类型；错误有稳定 code；破坏性变更需评审并升 API 前缀版本（/api/v1）。
- 鉴权：除标注外全部要求 `Authorization: Bearer <token>`；失败统一 `401 {"ok":false,"error":{"code":"auth_required"}}`。
- 成功包络：`{"ok": true, "data": …}`；错误包络：`{"ok": false, "error": {"code": "<stable_code>", "message": "<中文可读>"}}`。

## 稳定错误码
`auth_required` `invalid_token` `conflict_process_running` `conflict_install_in_progress` `version_not_ready` `version_not_installed` `version_in_use` `path_forbidden` `invalid_launch_args` `invalid_workflow` `download_failed` `checksum_mismatch` `disk_insufficient` `port_conflict` `plugin_update_failed` `index_unavailable` `internal`

## 端点

### API-001 健康检查（自升级用）
方法/路径：GET `/api/health`
认证：无，但仅接受 127.0.0.1 来源。
响应：`{"ok":true,"data":{"version":"2026.10.10","uptime_s":120}}`

### API-002 令牌校验（登录页）
方法/路径：POST `/api/auth/verify`
请求：`{"token":"…"}`（body 传递避免 URL 泄露）
响应：`{"ok":true,"data":{"panel_version":"2026.10.10"}}`
错误：`invalid_token`

### API-003 重新生成令牌
方法/路径：POST `/api/auth/rotate`
响应：`{"ok":true,"data":{"token":"<新令牌明文，仅此一次返回>"}}`
备注：旧令牌立即失效；响应与日志不回显旧令牌。

### API-004 ComfyUI 进程状态
方法/路径：GET `/api/comfy/status`
响应：
```json
{"ok":true,"data":{
  "state":"running|starting|stopping|stopped|failed",
  "pid":12345,"started_at":"2026-10-11T10:00:00Z","exit_code":null,
  "version":"0.39.0","current":"0.39.0","port":8188,"port_ready":true,
  "open_url":"https://…8188 映射域名提示（可空）"}}
```

### API-005 启动 / 停止 / 重启
方法/路径：POST `/api/comfy/start`｜`/api/comfy/stop`｜`/api/comfy/restart`
请求体：无（start 使用当前 LaunchConfig）。
响应：`{"ok":true,"data":{"state":"starting"}}`
错误：start → `conflict_process_running`（非 stopped）；`version_not_installed`（无 current）；`invalid_launch_args`；`port_conflict`。stop/restart 对 stopped 进程幂等成功。

### API-006 ComfyUI 日志
方法/路径：GET `/api/comfy/logs?tail=300`（历史环形缓冲）
响应：`{"ok":true,"data":{"lines":["…"],"cursor":1200}}`
实时流走 API-020 SSE。

### API-007 启动配置
方法/路径：GET `/api/comfy/launch-config`｜PUT 同路径
请求（PUT）：
```json
{"listen_port":8188,"listen_host":"127.0.0.1","preset":"low_vram","extra_args":"--disable-auto-launch",
 "academic_accel":true}
```
`listen_host`：`127.0.0.1`（默认，仅本机）｜`0.0.0.0`（对外暴露——供外部 API 调用，配合 AutoDL 6008 公网映射；**ComfyUI 无内置鉴权，URL 必须保密**）。
响应：回显已保存配置 + `{"warnings":["extra_args 中未识别的参数：…"]}`
错误：`invalid_launch_args`（端口越界/非法字符/与面板端口冲突）；`listen_host` 非枚举值 → 422。
预设枚举：`default | low_vram | fp16_fast | custom`（PUT 带 preset≠custom 时服务端展开参数并回填 extra_args）。

### API-008 系统状态
方法/路径：GET `/api/system/status`
响应：
```json
{"ok":true,"data":{
 "gpu":{"name":"RTX 4090","count":1,"driver":"550.127","vram_total_mb":24564,
        "vram_used_mb":16688,"available":true,"error":null},
 "memory":{"limit_mb":2048,"used_mb":812,"host_total_mb":772608},
 "disk":{"sys_total_gb":30,"sys_free_gb":12.4,"data_total_gb":50,"data_free_gb":41.0},
 "cuda":{"available":true,"version":"12.1"},
 "python_version":"3.11.6",
 "comfy_process":"running"}}
```
单源失败：对应子对象 `available:false / error:"…"`，整体仍 200。

### API-009 版本总览
方法/路径：GET `/api/versions`
响应：
```json
{"ok":true,"data":{
 "current":"0.39.0",
 "installed":[{"version":"0.39.0","installed_at":"…","disk_size_mb":4200,"status":"ready"}],
 "available":[{"version":"0.40.0","release_date":"2026-10-01","torch_baseline":"2.4",
   "size_mb":4100,"notes":"…","deprecated":false,"installed":false}],
 "index_cached_at":"2026-10-11T09:00:00Z","index_stale":false}}
```
索引不可达时 `available` 用缓存并置 `index_stale:true`；无缓存则 `index_unavailable`。

### API-010 版本操作
- POST `/api/versions/refresh` → 重新拉索引。
- POST `/api/versions/{version}/install` → `202 {"ok":true,"data":{"task":"install:0.40.0"}}`；进行中再装 → `conflict_install_in_progress`；磁盘不足 → `disk_insufficient`。
- POST `/api/versions/{version}/switch` → 进程非 stopped → `conflict_process_running`；未安装 → `version_not_installed`。成功 `{"ok":true,"data":{"current":"0.40.0"}}`。
- DELETE `/api/versions/{version}` → 当前版本/运行中 → `version_in_use`；未装 → `version_not_installed`。

### API-011 插件列表
方法/路径：GET `/api/plugins`
响应：
```json
{"ok":true,"data":{"items":[{
 "name":"ComfyUI-Manager","dir_name":"ComfyUI-Manager","enabled":true,
 "summary":"…","git_url":"https://github.com/…","update_status":"up_to_date",
 "has_remote":true,"version_hint":"3.31"}]}}
```

### API-012 插件操作
- POST `/api/plugins/{dir_name}/update` → `plugin_update_failed`（含原因：冲突/无远程/无 git）。
- POST `/api/plugins/{dir_name}/enable`｜`/disable` → 目录改名法；幂等。

### API-013 工作流列表与库
- GET `/api/workflows` → 本地已导入条目（含 `dependency_report`）。
- GET `/api/workflows/library` → 官方库条目 + `library_cached_at/library_stale`；带 `?refresh=1` 时强制重拉（也可用 POST `/api/workflows/refresh-library`）。

### API-014 工作流导入/上传/删除
- POST `/api/workflows/import` 请求：`{"slug":"flux-portrait"}` → 幂等覆盖更新；响应含 `dependency_report`。
- POST `/api/workflows/upload`（multipart：file）→ 校验失败 `invalid_workflow`；>5MB 或非 .json → `invalid_workflow`。
- DELETE `/api/workflows/{workflow_id}` → 幂等成功。
`dependency_report` 条目：`{"model_file":"flux1-dev-fp8.safetensors","category":"checkpoints","present":false,"suggest_dir":"/root/autodl-tmp/launchpad-data/shared/models/checkpoints"}`

### API-015 面板更新
- GET `/api/panel/update` → `{"current_version":"2026.10.07","latest_version":"2026.10.10","available":true,"notes":"…","checking":false}`
- POST `/api/panel/update` → `202 {"ok":true,"data":{"phase":"downloading"}}`；随后经 SSE `panel_event` 推送 phase：`downloading → staging → switching → done | rolled_back`。失败终态 `rolled_back` 附原因，面板保持旧版可用。

### API-016 面板日志
方法/路径：GET `/api/panel/logs?level=INFO&tail=500`
响应：`{"ok":true,"data":{"lines":["…"]}}`

### API-017 设置
- GET `/api/panel/settings` → `{panel_port, academic_accel_default, theme, autostart_enabled, channels{…}}`（不含令牌）。
- PUT `/api/panel/settings` → 部分更新，白名单字段；`panel_port` 变更需重启面板，响应带 `{"restart_required":true}`。

### API-020 SSE 事件流
方法/路径：GET `/api/events`（text/event-stream）
订阅参数：`?topics=process,logs,downloads,versions,panel`
事件：
```
event: process_state   data: {"state":"running","pid":123}
event: log             data: {"source":"comfy|panel","line":"…"}
event: download_progress data: {"task":"install:0.40.0","received":1234567,"total":4200000,"speed_bps":…}
event: version_event   data: {"kind":"installed|switched|removed","version":"0.40.0"}
event: panel_event     data: {"phase":"switching"} / {"phase":"rolled_back","reason":"…"}
```
心跳 15s；断线前端指数退避重连。

## 领域命令
（见 DOMAIN_MODEL「命令」节；API 路由是其唯一外部入口，一一对应或组合。）

## 事件
（见上 SSE；领域事件总线 → SSE 转发，事件不持久化。）

## 版本化
- API 前缀 `/api/v1/…`（MVP 实现即带 v1 前缀；本文省略书写）。
- 破坏性变更：升 `/api/v2` 并保留 v1 一个面板大版本周期。
- SSE 事件新增字段为非破坏；新增 topic 非破坏。
