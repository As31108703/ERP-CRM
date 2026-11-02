import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory } from "vue-router";
import App from "../src/App.vue";
import { createAppRouter } from "../src/router";
import { json } from "./overviewHarness";
import { workspace } from "./pageHarness";

const FAIL = { error: { code: "internal_error", message: "伺服器暫時無法回應" } };

/** 讓 view 端點依序回應：先失敗，之後回傳指定的工作區；其他端點一律 404。 */
function stubFetch(next: () => unknown) {
  let failing = true;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url !== "/api/v1/workspace/view") return json(404, { error: { code: "not_found", message: "找不到資源" } });
      if (failing) return json(500, FAIL);
      return json(200, { workspace: next(), csrf: "c", version: 1, report: null });
    }),
  );
  return () => {
    failing = false;
  };
}

async function mountApp(path: string) {
  const router = createAppRouter(createMemoryHistory());
  const wrapper = mount(App, { global: { plugins: [router] }, attachTo: document.body });
  await router.push(path);
  await flushPromises();
  return { wrapper, router };
}

beforeEach(() => setActivePinia(createPinia()));
afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("failed first load", () => {
  it("shows the error with a retry instead of routing to /build, then resumes the route", async () => {
    const recover = stubFetch(() => workspace());
    const { wrapper, router } = await mountApp("/overview");
    expect(router.currentRoute.value.path).toBe("/overview");
    const panel = wrapper.get("[data-testid=load-failed]");
    expect(panel.text()).toContain("伺服器暫時無法回應");
    // 錯誤只顯示在這個面板，不再另外出現同一則全域通知。
    expect(wrapper.text().match(/伺服器暫時無法回應/g)).toHaveLength(1);

    recover();
    await panel.get("[data-testid=load-retry]").trigger("click");
    await flushPromises();
    expect(wrapper.find("[data-testid=load-failed]").exists()).toBe(false);
    expect(router.currentRoute.value.path).toBe("/overview");
  });

  it("after a successful retry with no workspace, the usual /build redirect applies", async () => {
    const recover = stubFetch(() => null);
    const { wrapper, router } = await mountApp("/reports");
    expect(router.currentRoute.value.path).toBe("/reports");
    recover();
    await wrapper.get("[data-testid=load-retry]").trigger("click");
    await flushPromises();
    expect(wrapper.find("[data-testid=load-failed]").exists()).toBe(false);
    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe("/build"));
  });
});
