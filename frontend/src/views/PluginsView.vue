<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useMessage } from "naive-ui";
import { RefreshCw } from "lucide-vue-next";
import { api, type PluginItem } from "../api/client";

const message = useMessage();
const items = ref<PluginItem[]>([]);
const loading = ref(true);
const checking = ref(false);
const busy = ref<string | null>(null);

async function load(checkUpdates = false): Promise<void> {
  if (checkUpdates) checking.value = true;
  try {
    const data = await api.plugins(checkUpdates);
    items.value = data.items;
  } catch (e) {
    message.error(e instanceof Error ? e.message : "加载失败");
  } finally {
    loading.value = false;
    checking.value = false;
  }
}

async function update(p: PluginItem): Promise<void> {
  busy.value = p.dir_name;
  try {
    const r = await api.updatePlugin(p.dir_name);
    message.success(r.message);
    await load();
  } catch (e) {
    message.error(e instanceof Error ? e.message : "更新失败");
  } finally {
    busy.value = null;
  }
}

async function setEnabled(p: PluginItem, enabled: boolean): Promise<void> {
  busy.value = p.dir_name;
  try {
    const r = await api.enablePlugin(p.dir_name, enabled);
    message.success(r.message);
    await load();
  } catch (e) {
    message.error(e instanceof Error ? e.message : "操作失败");
  } finally {
    busy.value = null;
  }
}

function statusTag(p: PluginItem): { label: string; type: "success" | "warning" | "default" } {
  if (!p.has_remote) return { label: "本地安装", type: "default" };
  if (p.update_status === "behind") return { label: "可更新", type: "warning" };
  if (p.update_status === "up_to_date") return { label: "最新", type: "success" };
  return { label: "未知", type: "default" };
}

onMounted(() => load());
</script>

<template>
  <div>
    <n-card size="small" style="margin-bottom: 12px">
      <n-space justify="space-between" align="center">
        <n-text depth="3">插件按当前 ComfyUI 版本存放；启用/禁用重启后生效</n-text>
        <n-button :loading="checking" @click="load(true)">
          <template #icon><RefreshCw :size="15" /></template>
          检查更新
        </n-button>
      </n-space>
    </n-card>

    <n-spin :show="loading">
      <n-empty
        v-if="!loading && items.length === 0"
        description="当前版本还没有安装任何插件（可用 ComfyUI-Manager 或 git clone 到 custom_nodes）"
        style="padding: 60px 0"
      />
      <n-grid :cols="2" :x-gap="12" :y-gap="12" item-responsive responsive="screen">
        <n-gi v-for="p in items" :key="p.dir_name" span="2 m:1">
          <n-card size="small" :title="p.name">
            <template #header-extra>
              <n-space :size="6" align="center">
                <n-tag v-if="!p.enabled" type="error" size="small">已禁用</n-tag>
                <n-tag :type="statusTag(p).type" size="small">{{ statusTag(p).label }}</n-tag>
              </n-space>
            </template>
            <n-space vertical :size="6">
              <n-text depth="2" style="font-size: 12px; min-height: 18px">
                {{ p.summary || "（无简介）" }}
              </n-text>
              <n-text depth="3" class="mono" style="font-size: 11px; word-break: break-all">
                {{ p.git_url || "无 git 远程" }}{{ p.git_ref ? ` @ ${p.git_ref}` : "" }}
              </n-text>
              <n-space :size="8" style="margin-top: 4px">
                <n-button
                  size="small"
                  type="primary"
                  :disabled="!p.has_remote || !p.enabled"
                  :loading="busy === p.dir_name"
                  @click="update(p)"
                >
                  更新
                </n-button>
                <n-button
                  v-if="p.enabled"
                  size="small"
                  quaternary
                  :loading="busy === p.dir_name"
                  @click="setEnabled(p, false)"
                >
                  禁用
                </n-button>
                <n-button
                  v-else
                  size="small"
                  quaternary
                  type="primary"
                  :loading="busy === p.dir_name"
                  @click="setEnabled(p, true)"
                >
                  启用
                </n-button>
              </n-space>
            </n-space>
          </n-card>
        </n-gi>
      </n-grid>
    </n-spin>
  </div>
</template>
