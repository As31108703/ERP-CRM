import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import App from "../src/App.vue";
import { useUiStore } from "../src/stores/ui";
import { useWorkspaceStore } from "../src/stores/workspace";
import { flush, workspace } from "./pageHarness";
import { json } from "./overviewHarness";

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

async function mountApp(path: string) {
  vi.stubGlobal("fetch", vi.fn(async () => json(200, { total: 0, items: [] })));
  setActivePinia(createPinia());
  const store = useWorkspaceStore();
  store.view = { workspace: workspace(), csrf: "c", version: 7 };
  store.loaded = true;
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/m/:module", name: "module", component: { render: () => null } },
      { path: "/:rest(.*)*", component: { render: () => null } },
    ],
  });
  await router.push(path);
  await router.isReady();
  const wrapper = mount(App, { global: { plugins: [router] }, attachTo: document.body });
  return { wrapper, router, store };
}

describe("app shell wiring", () => {
  it("shows the target notice and clears the target", async () => {
    const { wrapper, router } = await mountApp("/m/sales?target=order:o1");
    const notice = wrapper.get("[data-testid=target-notice]");
    expect(notice.text()).toContain("已定位到指定紀錄，篩選已清除。");
    await wrapper.get("[data-testid=target-clear]").trigger("click");
    await flush();
    expect(router.currentRoute.value.fullPath).toBe("/m/sales");
    expect(wrapper.find("[data-testid=target-notice]").exists()).toBe(false);
  });

  it("command bar opens search and quick create (mutually exclusive)", async () => {
    const { wrapper, store } = await mountApp("/overview");
    const ui = useUiStore();
    const searchBtn = wrapper.findAll("button").find((b) => b.text().includes("搜尋工作區"))!;
    await searchBtn.trigger("click");
    await flush();
    expect(ui.searchOpen).toBe(true);
    expect(document.body.querySelector("[data-testid=search-input]")).not.toBeNull();

    const quickBtn = wrapper.findAll("button").find((b) => b.text().includes("快速新增"))!;
    await quickBtn.trigger("click");
    await flush();
    expect(ui.searchOpen).toBe(false);
    expect(ui.quickCreateOpen).toBe(true);
    expect(document.body.querySelector("[data-testid=quick-create-dialog]")).not.toBeNull();

    // 版本變動（例如另一個操作完成）時關閉快速新增。
    store.view = { ...store.view!, version: 8 };
    await flush();
    expect(ui.quickCreateOpen).toBe(false);
  });
});
