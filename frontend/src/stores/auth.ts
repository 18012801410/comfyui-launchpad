import { defineStore } from "pinia";
import { clearToken, getToken, setToken, api } from "../api/client";

export const useAuthStore = defineStore("auth", {
  state: () => ({
    token: getToken(),
    panelVersion: "",
    checked: false,
  }),
  actions: {
    async verify(token: string): Promise<boolean> {
      const data = await api.verify(token);
      this.panelVersion = data.panel_version;
      this.token = token;
      setToken(token);
      this.checked = true;
      return true;
    },
    logout(): void {
      clearToken();
      this.token = "";
      this.checked = false;
    },
  },
});
