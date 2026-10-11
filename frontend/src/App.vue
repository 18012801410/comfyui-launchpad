<script setup lang="ts">
import { darkTheme, dateZhCN, zhCN } from "naive-ui";
import { computed, onMounted } from "vue";
import { useThemeStore } from "./stores/theme";

const theme = useThemeStore();
onMounted(() => theme.init());

const naiveTheme = computed(() => (theme.isDark ? darkTheme : null));

const overrides = computed(() => ({
  common: {
    primary: theme.isDark ? "#9d86ff" : "#7c5cfc",
    primaryHover: theme.isDark ? "#b09aff" : "#8f73ff",
    primaryPressed: theme.isDark ? "#8a6fff" : "#6b4be0",
    bodyColor: theme.isDark ? "#12141c" : "#f6f7fb",
    cardColor: theme.isDark ? "#1b1e2a" : "#ffffff",
    borderColor: theme.isDark ? "#2a2f3e" : "#e4e7ef",
    textColorBase: theme.isDark ? "#e8eaf2" : "#1f2330",
    textColor1: theme.isDark ? "#e8eaf2" : "#1f2330",
    textColor2: theme.isDark ? "#c3c8d6" : "#3d4354",
    textColor3: theme.isDark ? "#9aa1b5" : "#5a6172",
    successColor: theme.isDark ? "#3dd68c" : "#30a46c",
    warningColor: theme.isDark ? "#ffb224" : "#f5a524",
    errorColor: theme.isDark ? "#ff6369" : "#e5484d",
    borderRadius: "6px",
    borderRadiusSmall: "4px",
  },
}));
</script>

<template>
  <n-config-provider
    :theme="naiveTheme"
    :theme-overrides="overrides"
    :locale="zhCN"
    :date-locale="dateZhCN"
    style="height: 100%"
  >
    <n-dialog-provider>
      <n-message-provider>
        <router-view />
      </n-message-provider>
    </n-dialog-provider>
  </n-config-provider>
</template>
