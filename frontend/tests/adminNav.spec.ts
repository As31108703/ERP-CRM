import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, describe, expect, it } from "vitest";
import { defineComponent } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import { targetLocation } from "../src/lib/records";
import { useUiStore } from "../src/stores/ui";
import { useWorkspaceStore } from "../src/stores/workspace";
import { flush, workspace } from "./pageHarness";

afterEach(() => {
  document.body.innerHTML = "";
});

async function mountUi() {
  setActivePinia(createPinia());
  const store = useWorkspaceStore();
  store.view = { workspace: workspace({ modules: ["sales", "administration"] }), csrf: "c", version: 7 };
  store.loaded = true;
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/:rest(.*)*", component: { render: () => null } }],
  });
  await router.push("/overview");
  await router.isReady();
  let ui: ReturnType<typeof useUiStore> | null = null;
  mount(
    defineComponent({
      setup() {
        ui = useUiStore();
        return () => null;
      },
    }),
    { global: { plugins: [router] } },
  );
  return { ui: ui as unknown as ReturnType<typeof useUiStore>, router };
}

describe("administration navigation", () => {
  it("targetLocation sends administration records to /administration", () => {
    expect(targetLocation({ module: "administration", kind: "request", id: "r1" })).toEqual({
      path: "/administration",
      query: { target: "request:r1" },
    });
    // 一般模組維持 /m/<module>。
    expect(targetLocation({ module: "sales", kind: "order", id: "o1" }).path).toBe("/m/sales");
  });

  it("ui.navigateTo routes administration targets to /administration?target=<kind>:<id>", async () => {
    const { ui, router } = await mountUi();
    await ui.navigateTo({ module: "administration", kind: "shift", id: "sh-1" });
    await flush();
    expect(router.currentRoute.value.path).toBe("/administration");
    expect(router.currentRoute.value.query).toEqual({ target: "shift:sh-1" });

    await ui.navigateTo({ module: "sales", kind: "order", id: "o1" });
    await flush();
    expect(router.currentRoute.value.fullPath).toBe("/m/sales?target=order:o1");
  });
});
