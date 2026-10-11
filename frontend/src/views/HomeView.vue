<script setup lang="ts">
import {
  Play,
  Square,
  RotateCw,
  ExternalLink,
  Settings2,
  Cpu,
  HardDrive,
  MemoryStick,
  Monitor,
} from "lucide-vue-next";
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useMessage } from "naive-ui";
import {
  api,
  connectSse,
  type ComfyStatus,
  type LaunchConfig,
  type SystemStatus,
} from "../api/client";

const message = useMessage();

// ---------- 进程状态 ----------
const status = ref<ComfyStatus | null>(null);
const sys = ref<SystemStatus | null>(null);
const busy = ref<"start" | "stop" | "restart" | null>(null);
const sseConnected = ref(true);

const stateLabel: Record<string, string> = {
  stopped: "未运行",
  starting: "启动中",
  running: "运行中",
  stopping: "停止中",
  failed: "启动失败",
};

const stateType = computed((): "success" | "warning" | "error" | "default" => {
  switch (status.value?.state) {
    case "running":
      return "success";
    case "starting":
    case "stopping":
      return "warning";
    case "failed":
      return "error";
    default:
      return "default";
  }
});

const canStart = computed(
  () => status.value?.state === "stopped" || status.value?.state === "failed",
);
const canStop = computed(
  () => status.value?.state === "running" || status.value?.state === "starting",
);

async function refresh(): Promise<void> {
  try {
    status.value = await api.comfyStatus();
  } catch {
    /* 401 已由 client 处理 */
  }
}

async function refreshSystem(): Promise<void> {
  try {
    sys.value = await api.systemStatus();
  } catch {
    /* 静默 */
  }
}

async function doStart(): Promise<void> {
  busy.value = "start";
  try {
    status.value = await api.comfyStart();
    message.success("ComfyUI 启动指令已发出，请观察日志");
  } catch (e) {
    message.error(e instanceof Error ? e.message : "启动失败");
    await refresh();
  } finally {
    busy.value = null;
  }
}

async function doStop(): Promise<void> {
  busy.value = "stop";
  try {
    status.value = await api.comfyStop();
    message.success("已停止");
  } catch (e) {
    message.error(e instanceof Error ? e.message : "停止失败");
  } finally {
    busy.value = null;
  }
}

async function doRestart(): Promise<void> {
  busy.value = "restart";
  try {
    status.value = await api.comfyRestart();
    message.success("重启指令已发出");
  } catch (e) {
    message.error(e instanceof Error ? e.message : "重启失败");
  } finally {
    busy.value = null;
  }
}

// ---------- 启动参数抽屉 ----------
const showDrawer = ref(false);
const cfg = ref<LaunchConfig | null>(null);
const cfgWarnings = ref<string[]>([]);

async function openDrawer(): Promise<void> {
  cfg.value = await api.launchConfig();
  cfgWarnings.value = [];
  showDrawer.value = true;
}

async function saveCfg(): Promise<void> {
  if (!cfg.value) return;
  try {
    const saved = await api.saveLaunchConfig({
      listen_port: cfg.value.listen_port,
      listen_host: cfg.value.listen_host,
      preset: cfg.value.preset,
      extra_args: cfg.value.extra_args,
      academic_accel: cfg.value.academic_accel,
    });
    cfg.value = saved;
    cfgWarnings.value = saved.warnings ?? [];
    message.success("启动参数已保存，下次启动生效");
  } catch (e) {
    message.error(e instanceof Error ? e.message : "保存失败");
  }
}

// ---------- 日志（SSE + 历史缓冲） ----------
interface LogLine {
  cursor: string;
  ts: string;
  source: string;
  line: string;
}
const logs = ref<LogLine[]>([]);
const autoScroll = ref(true);
const logBox = ref<HTMLElement | null>(null);

function logClass(line: string): string {
  if (/ERROR|Traceback|CRITICAL/i.test(line)) return "log-line-error";
  if (/WARN/i.test(line)) return "log-line-warn";
  return "";
}

async function loadHistory(): Promise<void> {
  const data = await api.comfyLogs(300);
  logs.value = data.lines;
  scrollToBottom();
}

function scrollToBottom(): void {
  if (autoScroll.value && logBox.value) {
    requestAnimationFrame(() => {
      if (logBox.value) logBox.value.scrollTop = logBox.value.scrollHeight;
    });
  }
}

function onUserScroll(): void {
  if (!logBox.value) return;
  const nearBottom =
    logBox.value.scrollHeight - logBox.value.scrollTop - logBox.value.clientHeight < 40;
  autoScroll.value = nearBottom;
}

let stopSse: (() => void) | null = null;

onMounted(async () => {
  await Promise.all([refresh(), refreshSystem(), loadHistory()]);
  const poll = window.setInterval(refreshSystem, 5000);
  stopSse = connectSse(["process", "logs"], {
    onEvent: (topic, payload) => {
      if (topic === "process") {
        void refresh();
      } else if (topic === "logs" && typeof payload.line === "string") {
        logs.value.push({
          cursor: String(payload.cursor ?? logs.value.length),
          ts: "",
          source: String(payload.source ?? "comfy"),
          line: payload.line,
        });
        if (logs.value.length > 500) logs.value.splice(0, logs.value.length - 500);
        scrollToBottom();
      }
    },
    onStateChange: (connected) => {
      sseConnected.value = connected;
    },
  });
  onUnmounted(() => {
    window.clearInterval(poll);
  });
});

onUnmounted(() => {
  stopSse?.();
});

function fmtMb(v: number | null): string {
  if (v === null) return "—";
  return v >= 1024 ? `${(v / 1024).toFixed(1)} GB` : `${v} MB`;
}
</script>

<template>
  <div>
    <!-- 操作栏 -->
    <n-card size="small" style="margin-bottom: 12px">
      <n-space align="center" :size="12" wrap>
        <n-button
          type="primary"
          :disabled="!canStart || busy !== null"
          :loading="busy === 'start'"
          @click="doStart"
        >
          <template #icon><Play :size="16" /></template>
          启动 ComfyUI
        </n-button>
        <n-button :disabled="!canStop || busy !== null" :loading="busy === 'stop'" @click="doStop">
          <template #icon><Square :size="16" /></template>
          停止
        </n-button>
        <n-button
          :disabled="!canStop || busy !== null"
          :loading="busy === 'restart'"
          @click="doRestart"
        >
          <template #icon><RotateCw :size="16" /></template>
          重启
        </n-button>
        <n-divider vertical />
        <n-tag :type="stateType" size="large" round>
          {{ stateLabel[status?.state ?? "stopped"] }}
          <span v-if="status?.version" style="margin-left: 6px; opacity: 0.8">
            v{{ status.version }}
          </span>
        </n-tag>
        <n-divider vertical />
        <n-button quaternary @click="openDrawer">
          <template #icon><Settings2 :size="16" /></template>
          启动参数
        </n-button>
        <n-tooltip>
          <template #trigger>
            <n-button
              tag="a"
              :href="status?.port_ready ? '/index.html' : undefined"
              target="_blank"
              :disabled="!status?.port_ready"
            >
              <template #icon><ExternalLink :size="16" /></template>
              打开 ComfyUI
            </n-button>
          </template>
          {{
            status?.port_ready
              ? "在新标签页打开 ComfyUI 界面（经由面板网关，公网可用）"
              : "ComfyUI 未运行"
          }}
        </n-tooltip>
      </n-space>
    </n-card>

    <!-- 状态卡 -->
    <n-grid :cols="4" :x-gap="12" :y-gap="12" style="margin-bottom: 12px" item-responsive responsive="screen">
      <n-gi span="4 s:2 m:1">
        <n-card size="small" title="GPU">
          <template #header-extra><Cpu :size="16" style="color: var(--lp-text-2)" /></template>
          <template v-if="sys?.gpu?.available">
            <div class="stat-big">{{ sys.gpu.name ?? "—" }}</div>
            <div class="stat-sub">
              显存 {{ fmtMb(sys.gpu.vram_used_mb) }} / {{ fmtMb(sys.gpu.vram_total_mb) }}
            </div>
          </template>
          <n-text v-else depth="3">不可用{{ sys?.gpu?.error ? `: ${sys.gpu.error}` : "" }}</n-text>
        </n-card>
      </n-gi>
      <n-gi span="4 s:2 m:1">
        <n-card size="small" title="驱动 / CUDA">
          <template #header-extra><Monitor :size="16" style="color: var(--lp-text-2)" /></template>
          <template v-if="sys?.gpu?.available">
            <div class="stat-big">{{ sys.gpu.driver ?? "—" }}</div>
            <div class="stat-sub">CUDA {{ sys.cuda?.version ?? "—" }}</div>
          </template>
          <n-text v-else depth="3">不可用</n-text>
        </n-card>
      </n-gi>
      <n-gi span="4 s:2 m:1">
        <n-card size="small" title="内存">
          <template #header-extra><MemoryStick :size="16" style="color: var(--lp-text-2)" /></template>
          <template v-if="sys?.memory?.limit_mb">
            <div class="stat-big">{{ fmtMb(sys.memory.used_mb) }}</div>
            <div class="stat-sub">
              限额 {{ fmtMb(sys.memory.limit_mb) }}
              <template v-if="sys.memory.host_total_mb">
                                / 宿主机 {{ fmtMb(sys.memory.host_total_mb) }}
              </template>
            </div>
          </template>
          <n-text v-else depth="3">不可用</n-text>
        </n-card>
      </n-gi>
      <n-gi span="4 s:2 m:1">
        <n-card size="small" title="磁盘">
          <template #header-extra><HardDrive :size="16" style="color: var(--lp-text-2)" /></template>
          <template v-if="sys?.disk?.data_free_gb !== null && sys?.disk">
            <div class="stat-big">数据盘 {{ sys.disk.data_free_gb }} GB 可用</div>
            <div class="stat-sub">
              系统 {{ sys.disk.sys_free_gb }} / {{ sys.disk.sys_total_gb }} GB
            </div>
          </template>
          <n-text v-else depth="3">不可用</n-text>
        </n-card>
      </n-gi>
    </n-grid>

    <!-- 运行日志 -->
    <n-card size="small" title="运行日志">
      <template #header-extra>
        <n-space :size="8" align="center">
          <n-tag v-if="!sseConnected" type="warning" size="small">连接断开，自动重连中</n-tag>
          <n-checkbox v-model:checked="autoScroll" size="small">自动滚动</n-checkbox>
          <n-button size="small" quaternary @click="loadHistory">刷新历史</n-button>
        </n-space>
      </template>
      <div ref="logBox" class="log-box mono" @scroll="onUserScroll">
        <n-empty v-if="logs.length === 0" description="暂无日志，启动 ComfyUI 后这里会实时滚动" style="padding: 40px 0" />
        <div v-for="(l, i) in logs" :key="i" :class="logClass(l.line)" class="log-line">{{ l.line }}</div>
      </div>
    </n-card>

    <!-- 启动参数抽屉 -->
    <n-drawer v-model:show="showDrawer" :width="420">
      <n-drawer-content title="启动参数" closable>
        <n-form v-if="cfg" label-placement="top">
          <n-form-item label="预设">
            <n-select
              v-model:value="cfg.preset"
              :options="[
                { label: '默认', value: 'default' },
                { label: '低显存（--lowvram）', value: 'low_vram' },
                { label: '极速 FP16（--force-fp16）', value: 'fp16_fast' },
                { label: '自定义', value: 'custom' },
              ]"
            />
          </n-form-item>
          <n-form-item label="监听端口">
            <n-input-number v-model:value="cfg.listen_port" :min="1024" :max="65535" style="width: 100%" />
          </n-form-item>
          <n-form-item label="监听地址">
            <n-radio-group v-model:value="cfg.listen_host">
              <n-radio value="127.0.0.1">仅本机（127.0.0.1）</n-radio>
              <n-radio value="0.0.0.0">对外暴露（0.0.0.0）</n-radio>
            </n-radio-group>
          </n-form-item>
          <n-alert
            v-if="cfg.listen_host === '0.0.0.0'"
            type="warning"
            :show-icon="false"
            style="margin-bottom: 12px"
          >
            <b>ComfyUI 没有内置鉴权</b>：对外暴露后，拿到公网 URL 的任何人都能用你的 GPU 生成图片、读取输出目录。
            外部 API 基址 = AutoDL 控制台中该端口（如 6008）映射的 https 域名；URL 请务必保密。
            更安全的做法是等面板提供鉴权网关后再对外。
          </n-alert>
          <n-form-item label="额外启动参数">
            <n-input
              v-model:value="cfg.extra_args"
              type="textarea"
              placeholder="如 --disable-auto-launch（空格分隔）"
              :autosize="{ minRows: 2, maxRows: 5 }"
            />
          </n-form-item>
          <n-form-item label="学术加速（启动时启用）">
            <n-switch v-model:value="cfg.academic_accel" />
          </n-form-item>
          <n-alert
            v-for="(w, i) in cfgWarnings"
            :key="i"
            type="warning"
            style="margin-bottom: 8px"
            :show-icon="false"
          >
            {{ w }}
          </n-alert>
        </n-form>
        <template #footer>
          <n-space justify="end">
            <n-button @click="showDrawer = false">取消</n-button>
            <n-button type="primary" @click="saveCfg">保存</n-button>
          </n-space>
        </template>
      </n-drawer-content>
    </n-drawer>
  </div>
</template>

<style scoped>
.stat-big {
  font-size: 18px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stat-sub {
  font-size: 12px;
  color: var(--lp-text-2);
  margin-top: 4px;
}

.log-box {
  height: 360px;
  overflow-y: auto;
  background: var(--lp-bg);
  border: 1px solid var(--lp-border);
  border-radius: 6px;
  padding: 12px;
  font-size: 12px;
  line-height: 1.7;
}

.log-line {
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
