import { createRouter, createWebHistory } from "vue-router";
import { getToken } from "../api/client";

export const router = createRouter({
  history: createWebHistory("/panel/"),
  routes: [
    {
      path: "/login",
      name: "login",
      component: () => import("../views/TokenGateView.vue"),
      meta: { public: true },
    },
    {
      path: "/",
      component: () => import("../layouts/AppShell.vue"),
      children: [
        { path: "", name: "home", component: () => import("../views/HomeView.vue") },
        { path: "versions", name: "versions", component: () => import("../views/VersionsView.vue") },
        { path: "plugins", name: "plugins", component: () => import("../views/PluginsView.vue") },
        { path: "workflows", name: "workflows", component: () => import("../views/WorkflowsView.vue") },
        { path: "settings", name: "settings", component: () => import("../views/SettingsView.vue") },
      ],
    },
  ],
});

router.beforeEach((to) => {
  if (!to.meta.public && !getToken()) {
    return { name: "login", query: { redirect: to.fullPath } };
  }
  if (to.name === "login" && getToken()) {
    return { name: "home" };
  }
  return true;
});
