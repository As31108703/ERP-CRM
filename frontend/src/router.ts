import { createRouter, createWebHashHistory, type RouterHistory, type RouteRecordRaw } from "vue-router";
import { usePreferencesStore } from "./stores/preferences";
import { MODULE_ROUTES } from "./lib/records";
import { useWorkspaceStore } from "./stores/workspace";

export { MODULE_ROUTES };

/** 沒有工作區時仍可進入的頁面，其他一律導向 /build。 */
export const SETUP_ROUTES = ["design", "custom", "capabilities", "blueprint", "build"] as const;

const Placeholder = () => import("./views/PlaceholderView.vue");
const DesignStudio = () => import("./modules/design/DesignStudio.vue");
const PAGES: Record<string, () => Promise<unknown>> = {
  design: DesignStudio,
  overview: () => import("./modules/overview/OverviewPage.vue"),
  learning: () => import("./modules/learning/LearningStudio.vue"),
  build: () => import("./modules/build/BuildWizard.vue"),
  custom: () => import("./modules/build/CustomSetup.vue"),
  capabilities: () => import("./modules/capabilities/CapabilityMap.vue"),
  blueprint: () => import("./modules/blueprint/BlueprintPage.vue"),
  administration: () => import("./modules/administration/AdminDesk.vue"),
  reports: () => import("./modules/reports/ReportsPage.vue"),
  settings: () => import("./modules/settings/SettingsPage.vue"),
};

const named: { name: string; title: string }[] = [
  { name: "build", title: "快速上手" },
  { name: "custom", title: "自訂建置" },
  { name: "overview", title: "工作總覽" },
  { name: "learning", title: "沉浸教學" },
  { name: "design", title: "主題圖庫" },
  { name: "capabilities", title: "功能地圖" },
  { name: "blueprint", title: "系統藍圖" },
  { name: "administration", title: "行政工作台" },
  { name: "reports", title: "模擬報表" },
  { name: "settings", title: "設定與資料" },
];

export const routes: RouteRecordRaw[] = [
  { path: "/", redirect: "/overview" },
  ...named.map(({ name, title }) => ({
    path: `/${name}`,
    name,
    component: PAGES[name] ?? Placeholder,
    meta: { title },
  })),
  {
    path: `/m/:module(${MODULE_ROUTES.join("|")})`,
    name: "module",
    component: () => import("./views/ModuleView.vue"),
    meta: { title: "模組" },
  },
  { path: "/:rest(.*)*", redirect: "/overview" },
];

export function createAppRouter(history: RouterHistory = createWebHashHistory()) {
  const router = createRouter({ history, routes });

  router.beforeEach(async (to) => {
    const store = useWorkspaceStore();
    await store.ready();
    const name = typeof to.name === "string" ? to.name : "";
    if (!store.hasWorkspace) {
      if (!(SETUP_ROUTES as readonly string[]).includes(name)) return { path: "/build" };
    } else if (name === "custom") {
      return { path: "/overview" };
    }
    return true;
  });

  // 前往主題圖庫以外的頁面即取消外觀試看（「到工作台看效果」那一次除外）。
  router.afterEach((to, _from, failure) => {
    if (failure) return;
    usePreferencesStore().navigated(typeof to.name === "string" ? to.name : "");
  });

  return router;
}
