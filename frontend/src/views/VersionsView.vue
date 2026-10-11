<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useMessage, useDialog } from "naive-ui";
import { RefreshCw } from "lucide-vue-next";
import {
  api,
  connectSse,
  type VersionsOverview,
} from "../api/client";

const message = useMessage();
const dialog = useDialog();

const data = ref<VersionsOverview | null>(null);
const loading = ref(true);
const refreshingIndex = ref(false);
const installing = ref<Set<string>>(new Set());
const installProgress = ref<Record<string, { received: number; total: number }>>({});
const busySwitch = ref<string | null>(null);

const running = computed(() => false); // 守卫权威在后端，此处仅控制体感禁用

async function load(): Promise<void> {
  loading.value = true;
  try {
    data.value = await api.versions();
  } finally {
    loading.value = false;
  }
}

async function refreshIndex(): Promise<void> {
  refreshingIndex.value = true;
  try {
    const r = await api.refreshVersionIndex();
    message.success(`索引已刷新（${r.count} 个版本）`);
    await load();
  } catch (e) {
    message.error(e instanceof Error ? e.message : "刷新失败");
  } finally {
    refreshingIndex.value = false;
  }
}

async function install(v: string): Promise<void> {
  installing.value.add(v);
  try {
    await api.installVersion(v);
    message.info(`版本 ${v} 开始下载安装，进度见卡片`);
  } catch (e) {
    message.error(e instanceof Error ? e.message : "安装失败");
    installing.value.delete(v);
  }
}

async function switchTo(v: string): Promise<void> {
  dialog.warning({
    title: "切换版本",
    content: `切换到 v${v}？模型与输出数据不受影响。`,
    positiveText: "切换",
    negativeText: "取消",
    onPositiveClick: async () => {
      busySwitch.value = v;
      try {
        await api.switchVersion(v);
        message.success(`已切换到 v${v}`);
        await load();
      } catch (e) {
        message.error(e instanceof Error ? e.message : "切换失败");
      } finally {
        busySwitch.value = null;
      }
    },
  });
}

async function remove(v: string): Promise<void> {
  dialog.error({
    title: "删除版本",
    content: `删除 v${v}？该版本目录将被移除（模型与输出不受影响），可重新下载。`,
    positiveText: "删除",
    negativeText: "取消",
    onPositiveClick: async () => {
      try {
        await api.deleteVersion(v);
        message.success(`已删除 v${v}`);
        await load();
      } catch (e) {
        message.error(e instanceof Error ? e.message : "删除失败");
      }
    },
  });
}

let stopSse: (() => void) | null = null;

onMounted(async () => {
  await load();
  stopSse = connectSse(["downloads", "versions"], {
    onEvent: async (topic, payload) => {
      if (topic === "downloads" && typeof payload.task === "string") {
        const v = payload.task.replace("install:", "");
        installProgress.value[v] = {
          received: Number(payload.received ?? 0),
          total: Number(payload.total ?? 0),
        };
      } else if (topic === "versions") {
        const v = String(payload.version ?? "");
        if (payload.kind === "installed") {
          installing.value.delete(v);
          delete installProgress.value[v];
          message.success(`版本 ${v} 安装完成`);
        }
        await load();
      }
    },
  });
});

onUnmounted(() => stopSse?.());

function pct(v: string): number {
  const p = installProgress.value[v];
  if (!p || !p.total) return 0;
  return Math.min(100, Math.round((p.received / p.total) * 100));
}
</script>

<template>
  <div>
    <n-card size="small" style="margin-bottom: 12px">
      <n-space align="center" justify="space-between">
        <n-space align="center">
          <n-tag type="primary" size="large">
            当前版本：{{ data?.current ? `v${data.current}` : "未安装" }}
          </n-tag>
          <n-tag v-if="data?.index_stale && data.available.length" type="warning" size="small">
            索引为缓存（{{ data.index_cached_at?.slice(0, 19).replace("T", " ") }}）
          </n-tag>
        </n-space>
        <n-button :loading="refreshingIndex" @click="refreshIndex">
          <template #icon><RefreshCw :size="15" /></template>
          刷新索引
        </n-button>
      </n-space>
    </n-card>

    <n-spin :show="loading">
      <n-empty
        v-if="!loading && data && data.available.length === 0 && data.installed.length === 0"
        description="还没有可用版本——点击「刷新索引」从渠道拉取"
        style="padding: 60px 0"
      >
        <template #extra>
          <n-button type="primary" @click="refreshIndex">刷新索引</n-button>
        </template>
      </n-empty>

      <n-grid :cols="3" :x-gap="12" :y-gap="12" item-responsive responsive="screen">
        <n-gi v-for="v in data?.available ?? []" :key="v.version" span="3 m:1">
          <n-card size="small" :title="`v${v.version}`">
            <template #header-extra>
              <n-tag v-if="v.version === data?.current" type="success" size="small">当前</n-tag>
              <n-tag v-else-if="v.installed" size="small">已安装</n-tag>
              <n-tag v-if="v.deprecated" type="warning" size="small">已弃用</n-tag>
            </template>
            <n-space vertical :size="6">
              <n-text depth="3" style="font-size: 12px">
                发布 {{ v.release_date || "—" }} · {{ v.size_mb ?? "—" }} MB · torch {{ v.torch_baseline || "—" }}
              </n-text>
              <n-text v-if="v.notes" depth="2" style="font-size: 12px">{{ v.notes }}</n-text>
              <n-progress
                v-if="installing.has(v.version)"
                type="line"
                :percentage="pct(v.version)"
                indicator-placement="inside"
                :height="14"
              />
              <n-space :size="8" style="margin-top: 4px">
                <n-button
                  v-if="!v.installed"
                  type="primary"
                  size="small"
                  :disabled="installing.has(v.version)"
                  :loading="installing.has(v.version)"
                  @click="install(v.version)"
                >
                  安装
                </n-button>
                <n-button
                  v-else-if="v.version !== data?.current"
                  size="small"
                  type="primary"
                  :loading="busySwitch === v.version"
                  @click="switchTo(v.version)"
                >
                  切换
                </n-button>
                <n-popconfirm
                  v-if="v.installed && v.version !== data?.current"
                  @positive-click="remove(v.version)"
                >
                  <template #trigger>
                    <n-button size="small" quaternary type="error">删除</n-button>
                  </template>
                  确认删除 v{{ v.version }}？
                </n-popconfirm>
              </n-space>
            </n-space>
          </n-card>
        </n-gi>
      </n-grid>

      <template v-if="data && data.installed.length > 0">
        <n-h3 style="margin: 20px 0 8px">已安装</n-h3>
        <n-list bordered>
          <n-list-item v-for="i in data.installed" :key="i.version">
            <n-space justify="space-between" align="center">
              <n-space align="center">
                <n-text strong>v{{ i.version }}</n-text>
                <n-tag v-if="i.version === data?.current" type="success" size="small">当前</n-tag>
                <n-text depth="3" style="font-size: 12px">
                  安装于 {{ i.installed_at?.slice(0, 19).replace("T", " ") ?? "—" }} · {{ i.disk_size_mb ?? "—" }} MB
                </n-text>
              </n-space>
            </n-space>
          </n-list-item>
        </n-list>
      </template>
    </n-spin>
  </div>
</template>
