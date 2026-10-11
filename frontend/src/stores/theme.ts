import { defineStore } from "pinia";
import { watch } from "vue";
import { api } from "../api/client";

const THEME_KEY = "launchpad_theme";
export type ThemeChoice = "system" | "light" | "dark";

function resolveDark(choice: ThemeChoice): boolean {
  if (choice === "dark") return true;
  if (choice === "light") return false;
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

export const useThemeStore = defineStore("theme", {
  state: () => ({
    choice: (localStorage.getItem(THEME_KEY) as ThemeChoice) || "system",
    isDark: false,
    /** 主题设置是否应同步到后端（登录后） */
    _syncTimer: 0,
  }),
  actions: {
    init(): void {
      this.apply();
      window
        .matchMedia("(prefers-color-scheme: dark)")
        .addEventListener("change", () => {
          if (this.choice === "system") this.apply();
        });
      watch(
        () => this.choice,
        () => {
          localStorage.setItem(THEME_KEY, this.choice);
          this.apply();
          this.syncToBackend();
        },
      );
    },
    apply(): void {
      this.isDark = resolveDark(this.choice);
      document.documentElement.classList.toggle("dark", this.isDark);
    },
    set(choice: ThemeChoice): void {
      this.choice = choice;
    },
    /** 登录后把本机选择同步到面板设置（失败静默） */
    async syncToBackend(): Promise<void> {
      try {
        await api.savePanelSettings({ theme: this.choice });
      } catch {
        /* 未登录或后端不可达时静默 */
      }
    },
  },
});
