# 设计系统（Design System）

## 设计原则
- 控制面板气质：清晰、可信、紧凑而不拥挤；状态一目了然。
- 紫色主色呼应 ComfyUI 品牌语境（参考面板同为紫罗兰系）。
- 暗色优先友好（GPU 机房用户常开暗色），但两主题同等公民。

## 组件库选型

| 决策 | 选择 | 原因 |
|---|---|---|
| 组件库 | Naive UI（Vue 3 + TS） | 无 CSS-in-JS 运行时负担轻、暗色主题一等公民、Tree-shakable、中文文档 |
| 图标 | lucide-vue-next | 风格统一线性图标 |
| 字体 | 系统栈 + JetBrains Mono（日志/代码） | 零加载成本 `[AI-DECIDED]` |

## 设计 Token

### 颜色（CSS variables，:root 与 .dark 两套）

| Token | 亮色值 | 暗色值 | 用途 |
|---|---|---|---|
| color/primary | #7C5CFC | #9D86FF | 主按钮、选中态、品牌 |
| color/primary-weak | #F0EDFF | #2A2550 | 选中底、徽标底 |
| color/bg | #F6F7FB | #12141C | 页面背景 |
| color/surface | #FFFFFF | #1B1E2A | 卡片/侧栏面 |
| color/text | #1F2330 | #E8EAF2 | 正文 |
| color/text-2 | #5A6172 | #9AA1B5 | 次级文字 |
| color/border | #E4E7EF | #2A2F3E | 描边/分隔 |
| color/success | #30A46C | #3DD68C | running/已导入/健康 |
| color/warning | #F5A524 | #FFB224 | starting/警告横幅 |
| color/danger | #E5484D | #FF6369 | failed/删除/ERROR 日志 |
| color/link | #4A6CF7 | #7C9BFF | 外链 |

### 字体

| Token | 值 | 用途 |
|---|---|---|
| font/family | -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif | UI |
| font/family-mono | "JetBrains Mono", Consolas, monospace | 日志、令牌、参数 |
| font/size-scale | 12 / 13 / 14（正文）/ 16 / 20 / 24 | 辅助/小/正文/卡片标题/页题/数字大 |
| font/weight-scale | 400 / 500（强调）/ 600（标题） | |

### 间距
基准单位：4px。刻度：4/8/12/16/24/32。卡片内边距 16，栅格间距 12，分节间距 24。

### 圆角/描边/阴影
- 圆角：控件 6px；卡片 10px；弹窗 12px。
- 描边 1px color/border；阴影仅浮层（弹窗/下拉）：0 8px 24px rgba(0,0,0,.12)（暗色加深）。

## 主题
- 亮/暗双主题；默认跟随系统（prefers-color-scheme），用户选择持久化。
- 可定制点（二期）：主色选择器。MVP 不暴露。

## 组件清单

### 组件：AppShell
变体：侧栏展开/折叠。
状态：无数据依赖，永不出错。
Token：color/surface（侧栏）、color/bg（主区）。
行为：侧栏底部常驻版本信息 + [检查更新] 红点提示。

### 组件：StatusCard
变体：GPU/驱动/显存/内存/磁盘/进程。
状态：加载中（骨架）/ 成功 / 错误（「不可用」+ 错误详情 tooltip）。
Token：surface、text、text-2、数字用 20/600。
行为：数值轮询刷新不闪屏（数字过渡）。

### 组件：LogConsole
变体：ComfyUI 日志 / 面板日志。
状态：连接中 / 流式 / 已断开（黄条）/ 空日志。
Token：surface、mono 字体、danger 高亮 ERROR、warning 高亮 WARN。
行为：默认自动滚动，用户上滚即暂停（[回到底部] 浮标）；DOM 上限 500 行。

### 组件：ActionBar
状态：各按钮随进程状态机启停（权威来自 /api/comfy/status）。
Token：primary（启动）、default（停止/重启）、link（打开 ComfyUI）。

### 组件：VersionCard / PluginCard / WorkflowCard
状态：见 UI_SPEC 各页状态节；进行中态必须按钮级。
Token：surface、border、success/danger 徽标。

### 组件：TokenGate
状态：校验中 / 错误（抖动 + 「令牌不正确」）/ 成功过场。
Token：primary、surface；令牌输入用 mono。

### 组件：ConfirmDialog / Toast / EmptyState / ErrorBanner / ProgressInline / Badge
遵循 Naive UI 对应组件 + 上述 Token 定制主题；Badge 一律「色点+文字」。

## 无障碍规则
- 对比度下限 4.5:1（正文）/ 3:1（大字号与图形）。
- 焦点可见性：2px primary 焦点环，永不移除。
- 键盘导航：侧栏与所有按钮可 Tab；Esc 关弹窗；日志区 focus 后可方向键滚动。
- 状态不单靠颜色：徽标必带文字。

## 推荐 / 禁止
- 推荐：数字变化用 transition；按钮级进行中反馈；错误给下一步动作（「去设置」「重试」）。
- 禁止：整页 loading 遮罩；纯图标无 aria-label；红绿作为唯一状态区分；在亮暗主题里硬编码色值（必须走 Token）。
