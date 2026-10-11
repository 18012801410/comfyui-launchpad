<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import { useMessage, useDialog } from "naive-ui";
import { RefreshCw, Download } from "lucide-vue-next";
import {
  api,
  connectSse,
  type PanelSettingsData,
  type PanelUpdateInfo,
} from "../api/client";
import { useThemeStore, type ThemeChoice } from "../stores/theme";

const message = useMessage();
const dialog = useDialog();
const theme = useThemeStore();

const settings = ref<PanelSettingsData | null>(null);
const loading = ref(true);

// 面板更新
const updateInfo = ref<PanelUpdateInfo | null>(null);
const updatePhase = ref<"idle" | "downloading" | "staging" | "switching" | "done" | "rolled_back">("idle");
const updateReason = ref("");
const checkingUpdate = ref(false);

// 面板日志
const panelLogs = ref<string>("");
const logLevel = ref<"INFO" | "WARNING" | "ERROR">("INFO");

async function load(): Promise<void> {
  try {
    settings.value = await api.panelSettings();
  } finally {
    loading.value = false;
  }
}

const channelUnavailable = ref("");

async function checkUpdate(): Promise<void> {
  checkingUpdate.value = true;
  channelUnavailable.value = "";
  try {
    updateInfo.value = await api.panelUpdateInfo();
  } catch (e) {
    // 渠道不可达是常见状态（首次部署/网络受限），页面内提示而非打断
    channelUnavailable.value = e instanceof Error ? e.message : "检查更新失败";
    updateInfo.value = {
      current_version: "—",
      latest_version: "—",
      available: false,
      notes: "",
      checking: false,
    };
  } finally {
    checkingUpdate.value = false;
  }
}

async function doUpdate(): Promise<void> {
  dialog.warning({
    title: "一键升级面板",
    content: `升级到 ${updateInfo.value?.latest_version}？升级期间 ComfyUI 不受影响；失败会自动回滚。`,
    positiveText: "立即升级",
    negativeText: "取消",
    onPositiveClick: async () => {
      updatePhase.value = "downloading";
      try {
        await api.panelUpdate();
      } catch (e) {
        message.error(e instanceof Error ? e.message : "升级发起失败");
        updatePhase.value = "idle";
      }
    },
  });
}

async function rotateToken(): Promise<void> {
  dialog.warning({
    title: "重新生成访问令牌",
    content: "所有已登录会话将立即失效（包括当前浏览器）。继续？",
    positiveText: "重新生成",
    negativeText: "取消",
    onPositiveClick: async () => {
      try {
        const r = await api.rotate();
        message.success("令牌已重新生成，请立即保存（仅显示一次）");
        dialog.success({
          title: "新令牌",
          content: r.token,
          positiveText: "已复制并保存",
          onPositiveClick: () => {
            navigator.clipboard?.writeText(r.token).catch(() => {});
          },
        });
      } catch (e) {
        message.error(e instanceof Error ? e.message : "生成失败");
      }
    },
  });
}

async function saveAutostart(v: boolean): Promise<void> {
  try {
    await api.savePanelSettings({ autostart_enabled: v });
    message.success(v ? "已开启（SSH 登录时自动拉起面板）" : "已关闭自启");
  } catch (e) {
    message.error(e instanceof Error ? e.message : "保存失败");
    await load();
  }
}

async function loadPanelLogs(): Promise<void> {
  try {
    const data = await api.panelLogs(500);
    const level = logLevel.value;
    panelLogs.value =
      level === "INFO"
        ? data.lines.join("\n")
        : data.lines
            .filter((l) => l.includes(level))
            .join("\n");
  } catch {
    panelLogs.value = "（面板日志不可读——生产环境由 supervisor 写入 logs/panel.log）";
  }
}

function downloadLogs(): void {
  const blob = new Blob([panelLogs.value], { type: "text/plain" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `launchpad-panel-${new Date().toISOString().slice(0, 10)}.log`;
  a.click();
  URL.revokeObjectURL(a.href);
}

let stopSse: (() => void) | null = null;

onMounted(async () => {
  await load();
  await checkUpdate();
  await loadPanelLogs();
  stopSse = connectSse(["panel"], {
    onEvent: async (topic, payload) => {
      if (topic !== "panel") return;
      const phase = String(payload.phase ?? "");
      updatePhase.value = phase as typeof updatePhase.value;
      if (phase === "rolled_back") {
        updateReason.value = String(payload.reason ?? "");
        message.error(`升级失败已回滚: ${updateReason.value}`);
        await checkUpdate();
      } else if (phase === "done") {
        message.success("升级完成，页面即将刷新");
        setTimeout(() => location.reload(), 1500);
      }
    },
  });
});

onUnmounted(() => stopSse?.());

const phaseLabel: Record<string, string> = {
  downloading: "下载发行包…",
  staging: "解压就位…",
  switching: "切换版本并重启…",
  done: "完成",
  rolled_back: "已回滚",
};

const themeOptions: { label: string; value: ThemeChoice }[] = [
  { label: "跟随系统", value: "system" },
  { label: "亮色", value: "light" },
  { label: "暗色", value: "dark" },
];
</script>

<template>
  <n-spin :show="loading">
    <n-space vertical :size="12">
      <!-- 访问令牌 -->
      <n-card title="访问令牌" size="small">
        <n-space align="center" justify="space-between">
          <n-text depth="2">
            令牌是面板的唯一凭证；重新生成后所有已登录会话立即失效
          </n-text>
          <n-button @click="rotateToken">重新生成令牌</n-button>
        </n-space>
      </n-card>

      <!-- 面板更新 -->
      <n-card title="面板更新" size="small">
        <n-space vertical :size="10">
          <n-space align="center" justify="space-between">
            <n-space align="center">
              <n-text strong>当前 {{ updateInfo?.current_version || "—" }}</n-text>
              <n-tag v-if="updateInfo?.available" type="warning">
                可升级到 {{ updateInfo.latest_version }}
              </n-tag>
              <n-tag v-else-if="updateInfo && !updateInfo.available" type="success">已是最新</n-tag>
            </n-space>
            <n-space :size="8">
              <n-button :loading="checkingUpdate" @click="checkUpdate">
                <template #icon><RefreshCw :size="15" /></template>
                检查更新
              </n-button>
              <n-button
                v-if="updateInfo?.available"
                type="primary"
                :disabled="updatePhase !== 'idle' && updatePhase !== 'rolled_back'"
                @click="doUpdate"
              >
                一键升级
              </n-button>
            </n-space>
          </n-space>
          <n-text v-if="updateInfo?.notes" depth="3" style="font-size: 12px; white-space: pre-wrap">
            {{ updateInfo.notes }}
          </n-text>
          <n-text v-if="channelUnavailable" depth="3" style="font-size: 12px">
            更新渠道不可达：{{ channelUnavailable }}
          </n-text>
          <n-alert
            v-if="updatePhase !== 'idle' && updatePhase !== 'done'"
            :type="updatePhase === 'rolled_back' ? 'error' : 'info'"
            :show-icon="false"
          >
            {{ phaseLabel[updatePhase] }}
            <span v-if="updatePhase === 'rolled_back'">：{{ updateReason }}</span>
          </n-alert>
        </n-space>
      </n-card>

      <!-- 外观与自启 -->
      <n-card title="外观与自启" size="small">
        <n-space :size="24" align="center">
          <n-space align="center">
            <n-text>主题</n-text>
            <n-select
              :value="theme.choice"
              :options="themeOptions"
              style="width: 140px"
              @update:value="(v: ThemeChoice) => theme.set(v)"
            />
          </n-space>
          <n-divider vertical />
          <n-space align="center">
            <n-text>开机自启（SSH 登录拉起）</n-text>
            <n-switch
              :value="settings?.autostart_enabled ?? true"
              @update:value="saveAutostart"
            />
          </n-space>
        </n-space>
      </n-card>

      <!-- 面板日志 -->
      <n-card title="面板日志" size="small">
        <template #header-extra>
          <n-space :size="8" align="center">
            <n-select
              v-model:value="logLevel"
              size="small"
              style="width: 110px"
              :options="[
                { label: 'INFO+', value: 'INFO' },
                { label: 'WARNING+', value: 'WARNING' },
                { label: 'ERROR', value: 'ERROR' },
              ]"
              @update:value="loadPanelLogs"
            />
            <n-button size="small" @click="loadPanelLogs">刷新</n-button>
            <n-button size="small" @click="downloadLogs">
              <template #icon><Download :size="14" /></template>
              下载
            </n-button>
          </n-space>
        </template>
        <pre class="mono panel-logs">{{ panelLogs || "（暂无日志）" }}</pre>
      </n-card>
    </n-space>
  </n-spin>
</template>

<style scoped>
.panel-logs {
  max-height: 300px;
  overflow-y: auto;
  background: var(--lp-bg);
  border: 1px solid var(--lp-border);
  border-radius: 6px;
  padding: 12px;
  font-size: 12px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
