<script setup lang="ts">
import { Moon, Sun, Monitor } from "lucide-vue-next";
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useThemeStore } from "../stores/theme";

const route = useRoute();
const router = useRouter();
const theme = useThemeStore();

const navs = [
  { path: "/", label: "启动 ComfyUI" },
  { path: "/versions", label: "版本管理" },
  { path: "/plugins", label: "插件管理" },
  { path: "/workflows", label: "工作流管理" },
  { path: "/settings", label: "系统设置" },
];

const activeKey = computed(() => route.path);
const isDark = computed(() => theme.isDark);

function toggleTheme(): void {
  theme.set(theme.isDark ? "light" : "dark");
}

function themeLabel(): string {
  return theme.choice === "dark" ? "切换到亮色" : "切换到暗色";
}
</script>

<template>
  <n-layout has-sider style="height: 100vh">
    <n-layout-sider
      bordered
      collapse-mode="width"
      :collapsed-width="64"
      :width="220"
      show-trigger
      :native-scrollbar="false"
      style="background: var(--lp-surface)"
    >
      <div class="brand">
        <div class="brand-name">LaunchPad</div>
        <div class="brand-sub">COMFYUI 启动台</div>
      </div>
      <n-menu
        :value="activeKey"
        :options="navs.map((n) => ({ label: n.label, key: n.path }))"
        :indent="18"
        @update:value="(key: string) => router.push(key)"
      />
      <div class="sidebar-footer">
        <n-text depth="3" style="font-size: 12px">
          面板运行中 · 令牌已验证
        </n-text>
      </div>
    </n-layout-sider>

    <n-layout :native-scrollbar="false">
      <n-layout-header bordered style="height: 52px; display: flex; align-items: center; padding: 0 24px; justify-content: space-between; background: var(--lp-surface)">
        <div style="font-weight: 600; font-size: 16px">
          {{ navs.find((n) => n.path === activeKey)?.label ?? "ComfyUI LaunchPad" }}
        </div>
        <n-space :size="8" align="center">
          <n-tooltip>
            <template #trigger>
              <n-button quaternary circle :aria-label="themeLabel()" @click="toggleTheme">
                <template #icon>
                  <Moon v-if="!isDark" :size="18" />
                  <Sun v-else :size="18" />
                </template>
              </n-button>
            </template>
            {{ themeLabel() }}（当前: {{ theme.choice === "system" ? "跟随系统" : theme.choice }}）
          </n-tooltip>
          <n-tooltip>
            <template #trigger>
              <n-button quaternary circle aria-label="跟随系统主题" @click="theme.set('system')">
                <template #icon>
                  <Monitor :size="18" />
                </template>
              </n-button>
            </template>
            跟随系统主题
          </n-tooltip>
        </n-space>
      </n-layout-header>
      <n-layout-content content-style="padding: 24px; min-height: calc(100vh - 52px);">
        <div class="page-container">
          <router-view />
        </div>
      </n-layout-content>
    </n-layout>
  </n-layout>
</template>

<style scoped>
.brand {
  padding: 20px 22px 8px;
}

.brand-name {
  font-size: 20px;
  font-weight: 700;
  color: var(--lp-primary);
  letter-spacing: 0.5px;
}

.brand-sub {
  font-size: 11px;
  color: var(--lp-text-2);
  letter-spacing: 2px;
  margin-top: 2px;
}

.sidebar-footer {
  padding: 16px 22px;
  margin-top: 24px;
}

.page-container {
  max-width: 1280px;
  margin: 0 auto;
}
</style>
