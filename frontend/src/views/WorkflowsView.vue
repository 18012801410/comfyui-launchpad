<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useMessage } from "naive-ui";
import { RefreshCw, Upload } from "lucide-vue-next";
import {
  api,
  type LibraryWorkflow,
  type WorkflowItem,
} from "../api/client";

const message = useMessage();
const tab = ref<"library" | "mine">("library");

// 官方库
const library = ref<LibraryWorkflow[]>([]);
const libLoading = ref(true);
const libStale = ref(false);
const importing = ref<string | null>(null);
const importedSlugs = ref<Set<string>>(new Set());

// 我的工作流
const mine = ref<WorkflowItem[]>([]);
const mineLoading = ref(false);
const uploading = ref(false);

const missingCount = (item: WorkflowItem): number =>
  item.dependency_report.filter((d) => !d.present).length;

async function loadLibrary(refresh = false): Promise<void> {
  libLoading.value = true;
  try {
    const data = await api.workflowLibrary(refresh);
    library.value = data.workflows;
    libStale.value = data.stale;
  } catch (e) {
    message.error(e instanceof Error ? e.message : "官方库加载失败");
  } finally {
    libLoading.value = false;
  }
}

async function loadMine(): Promise<void> {
  mineLoading.value = true;
  try {
    mine.value = (await api.workflows()).items;
    importedSlugs.value = new Set(
      mine.value.map((m) => m.library_slug).filter((s): s is string => s !== null),
    );
  } finally {
    mineLoading.value = false;
  }
}

async function importWf(w: LibraryWorkflow): Promise<void> {
  importing.value = w.slug;
  try {
    const item = await api.importWorkflow(w.slug);
    const missing = missingCount(item);
    message.success(
      missing > 0 ? `已导入「${w.name}」，注意有 ${missing} 个依赖模型缺失` : `已导入「${w.name}」`,
    );
    await loadMine();
  } catch (e) {
    message.error(e instanceof Error ? e.message : "导入失败");
  } finally {
    importing.value = null;
  }
}

async function onUpload(e: Event): Promise<void> {
  const input = e.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  uploading.value = true;
  try {
    const item = await api.uploadWorkflow(file);
    message.success(`已上传「${item.name}」`);
    await loadMine();
  } catch (err) {
    message.error(err instanceof Error ? err.message : "上传失败");
  } finally {
    uploading.value = false;
    input.value = "";
  }
}

async function removeWf(item: WorkflowItem): Promise<void> {
  try {
    await api.deleteWorkflow(item.workflow_id);
    message.success(`已删除「${item.name}」`);
    await loadMine();
  } catch (e) {
    message.error(e instanceof Error ? e.message : "删除失败");
  }
}

function showDeps(item: WorkflowItem): void {
  const lines = item.dependency_report
    .map(
      (d) =>
        `${d.present ? "✓" : "✗"} ${d.model_file}（${d.category}${d.present ? "" : `，放 ${d.suggest_dir}`}）`,
    )
    .join("\n");
  dialog.info({
    title: `依赖模型：${item.name}`,
    content: lines || "该工作流没有解析出模型依赖",
    positiveText: "知道了",
  });
}

import { useDialog } from "naive-ui";
const dialog = useDialog();

onMounted(async () => {
  await Promise.all([loadLibrary(), loadMine()]);
});
</script>

<template>
  <div>
    <n-card size="small" style="margin-bottom: 12px">
      <n-tabs v-model:value="tab" type="line" style="margin-top: -14px">
        <n-tab name="library" tab="官方工作流库" />
        <n-tab name="mine" tab="我的工作流" />
      </n-tabs>
      <n-space justify="space-between" align="center" style="margin-top: 4px">
        <n-text v-if="tab === 'library' && libStale" depth="3" style="font-size: 12px">
          官方库为缓存数据，点「刷新库」获取最新
        </n-text>
        <span v-else />
        <n-space :size="8">
          <template v-if="tab === 'library'">
            <n-button :loading="libLoading" @click="loadLibrary(true)">
              <template #icon><RefreshCw :size="15" /></template>
              刷新库
            </n-button>
          </template>
          <template v-else>
            <label>
              <n-button tag="span" type="primary" :loading="uploading">
                <template #icon><Upload :size="15" /></template>
                上传 JSON
              </n-button>
              <input type="file" accept=".json" style="display: none" @change="onUpload" />
            </label>
          </template>
        </n-space>
      </n-space>
    </n-card>

    <!-- 官方库 -->
    <n-spin v-if="tab === 'library'" :show="libLoading">
      <n-empty
        v-if="!libLoading && library.length === 0"
        description="官方库为空或索引不可达——点「刷新库」重试"
        style="padding: 60px 0"
      />
      <n-grid :cols="3" :x-gap="12" :y-gap="12" item-responsive responsive="screen">
        <n-gi v-for="w in library" :key="w.slug" span="3 m:1">
          <n-card size="small" :title="w.name">
            <template #header-extra>
              <n-tag size="small" v-if="w.category">{{ w.category }}</n-tag>
            </template>
            <n-space vertical :size="6">
              <n-text depth="2" style="font-size: 12px; min-height: 32px">{{ w.description }}</n-text>
              <n-text depth="3" style="font-size: 12px">更新于 {{ w.updated_at || "—" }}</n-text>
              <n-button
                size="small"
                type="primary"
                :loading="importing === w.slug"
                @click="importWf(w)"
              >
                {{ importedSlugs.has(w.slug) ? "重新导入（覆盖）" : "导入" }}
              </n-button>
            </n-space>
          </n-card>
        </n-gi>
      </n-grid>
    </n-spin>

    <!-- 我的工作流 -->
    <n-spin v-if="tab === 'mine'" :show="mineLoading">
      <n-empty
        v-if="!mineLoading && mine.length === 0"
        description="还没有工作流——从官方库导入或上传自己的 JSON"
        style="padding: 60px 0"
      />
      <n-list v-else bordered>
        <n-list-item v-for="item in mine" :key="item.workflow_id">
          <n-space justify="space-between" align="center">
            <n-space align="center">
              <n-tag :type="item.source === 'official' ? 'primary' : 'default'" size="small">
                {{ item.source === "official" ? "官方库" : "上传" }}
              </n-tag>
              <n-text strong>{{ item.name }}</n-text>
              <n-text depth="3" style="font-size: 12px">
                {{ item.imported_at.slice(0, 19).replace("T", " ") }}
              </n-text>
              <n-tag v-if="missingCount(item) > 0" type="warning" size="small">
                缺 {{ missingCount(item) }} 个模型
              </n-tag>
              <n-tag v-else-if="item.dependency_report.length" type="success" size="small">
                依赖齐全
              </n-tag>
            </n-space>
            <n-space :size="8">
              <n-button size="small" quaternary @click="showDeps(item)">查看依赖</n-button>
              <n-popconfirm @positive-click="removeWf(item)">
                <template #trigger>
                  <n-button size="small" quaternary type="error">删除</n-button>
                </template>
                确认删除「{{ item.name }}」？
              </n-popconfirm>
            </n-space>
          </n-space>
        </n-list-item>
      </n-list>
    </n-spin>
  </div>
</template>
