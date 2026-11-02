import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function stubView(workspace: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) =>
      url === "/api/v1/workspace/view"
        ? json(200, { workspace, csrf: "c", version: workspace ? 1 : 0, report: null })
        : json(404, { error: { code: "not_found", message: "找不到資源" } }),
    ),
  );
}

async function makeRouter() {
  const { createAppRouter } = await import("../src/router");
  const { createMemoryHistory } = await import("vue-router");
  return createAppRouter(createMemoryHistory());
}

describe("router", () => {
  beforeEach(() => {
    vi.resetModules();
    setActivePinia(createPinia());
  });
  afterEach(() => vi.unstubAllGlobals());

  it("without a workspace only setup-side pages are reachable", async () => {
    stubView(null);
    const router = await makeRouter();
    for (const path of ["/design", "/custom", "/capabilities", "/blueprint", "/build"]) {
      await router.push(path);
      expect(router.currentRoute.value.path).toBe(path);
    }
    for (const path of ["/overview", "/m/crm", "/reports", "/settings", "/learning", "/administration"]) {
      await router.push(path);
      expect(router.currentRoute.value.path).toBe("/build");
    }
  });

  it("with a workspace module routes resolve and custom goes to overview", async () => {
    stubView({ generation_id: "g", version: 1, company_name: "甲", industry: "general", modules: ["crm"] });
    const router = await makeRouter();
    await router.push("/m/inventory");
    expect(router.currentRoute.value.params.module).toBe("inventory");
    await router.push("/custom");
    expect(router.currentRoute.value.path).toBe("/overview");
    await router.push("/m/unknown");
    expect(router.currentRoute.value.path).toBe("/overview");
    await router.push("/");
    expect(router.currentRoute.value.path).toBe("/overview");
  });
});
