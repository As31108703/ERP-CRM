import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const VIEW_WS = {
  workspace: { generation_id: "g1", version: 3, company_name: "星軌示範商店", industry: "general", modules: ["crm"] },
  csrf: "c1",
  version: 3,
  report: null,
};

function stubFetch() {
  const seen: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      seen.push(`${method} ${url}`);
      if (method === "GET" && url === "/api/v1/workspace/view") return json(200, VIEW_WS);
      if (method === "POST") return json(200, { result: "x", ...VIEW_WS });
      return json(404, { error: { code: "not_found", message: "找不到資源" } });
    }),
  );
  return seen;
}

async function stores() {
  const { useWorkspaceStore, DESIGN_PREVIEW_BLOCKED } = await import("../src/stores/workspace");
  const { usePreferencesStore } = await import("../src/stores/preferences");
  return { ws: useWorkspaceStore(), prefs: usePreferencesStore(), DESIGN_PREVIEW_BLOCKED };
}

const root = () => document.documentElement.dataset;

describe("preferences", () => {
  beforeEach(() => {
    vi.resetModules();
    setActivePinia(createPinia());
    window.localStorage.clear();
    window.sessionStorage.clear();
    delete root().themeId;
    delete root().theme;
    delete root().density;
  });
  afterEach(() => vi.unstubAllGlobals());

  it("preview blocks mutation and Esc cancels", async () => {
    const seen = stubFetch();
    const { ws, prefs, DESIGN_PREVIEW_BLOCKED } = await stores();
    await ws.refresh();
    expect(root().themeId).toBe("bridge");

    prefs.previewTheme("neon");
    expect(prefs.previewing).toBe(true);
    expect(root().themeId).toBe("neon");

    expect(await ws.run("POST", "/api/v1/crm/customers", { name: "甲" })).toBeNull();
    expect(ws.error).toBe(DESIGN_PREVIEW_BLOCKED);
    expect(seen.filter((s) => s.startsWith("POST"))).toHaveLength(0);

    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(prefs.previewing).toBe(false);
    expect(root().themeId).toBe("bridge");

    expect(await ws.run("POST", "/api/v1/crm/customers", { name: "甲" })).not.toBeNull();
    expect(seen.filter((s) => s.startsWith("POST"))).toHaveLength(1);
  });

  it("Esc inside a text field does not cancel the preview", async () => {
    stubFetch();
    const { prefs } = await stores();
    prefs.previewTheme("orbital");
    const input = document.createElement("input");
    document.body.appendChild(input);
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    expect(prefs.previewing).toBe(true);
    input.remove();
  });

  it("applyTheme stores {version:1, theme} and ends the preview", async () => {
    stubFetch();
    const { ws, prefs } = await stores();
    prefs.previewTheme("quantum");
    prefs.applyTheme("quantum");
    expect(prefs.previewing).toBe(false);
    expect(ws.designPreview).toBe(false);
    expect(prefs.themeId).toBe("quantum");
    expect(JSON.parse(window.localStorage.getItem("erpcrm.theme.v1")!)).toEqual({ version: 1, theme: "quantum" });
    expect(root().themeId).toBe("quantum");
    expect(ws.message).toContain("已套用「量子實驗室」");
  });

  it("defaults are bridge / system / comfortable and bad stored values fall back", async () => {
    window.localStorage.setItem("erpcrm.theme.v1", JSON.stringify({ version: 1, theme: "nope" }));
    window.localStorage.setItem("erpcrm.interface.v1", JSON.stringify({ theme: "dark", density: "x", extra: 1 }));
    stubFetch();
    const { prefs } = await stores();
    expect(prefs.themeId).toBe("bridge");
    expect(prefs.scheme).toBe("system");
    expect(prefs.density).toBe("comfortable");
  });

  it("scheme and density persist to erpcrm.interface.v1 and set data attributes", async () => {
    stubFetch();
    const { prefs } = await stores();
    prefs.setScheme("light");
    prefs.setDensity("compact");
    expect(JSON.parse(window.localStorage.getItem("erpcrm.interface.v1")!)).toEqual({
      theme: "light",
      density: "compact",
    });
    expect(root().theme).toBe("light");
    expect(root().density).toBe("compact");
    prefs.setScheme("dark");
    expect(root().theme).toBe("dark");
  });

  it("leaving the design page cancels the preview unless kept for 到工作台看效果", async () => {
    stubFetch();
    const { prefs } = await stores();
    const { createAppRouter } = await import("../src/router");
    const { createMemoryHistory } = await import("vue-router");
    const router = createAppRouter(createMemoryHistory());
    await router.push("/design");
    prefs.previewTheme("foundry");
    await router.push("/capabilities");
    expect(prefs.previewing).toBe(false);

    await router.push("/design");
    prefs.previewTheme("nebula");
    prefs.keepPreviewForNextNavigation();
    await router.push("/overview");
    expect(prefs.previewing).toBe(true);
    expect(root().themeId).toBe("nebula");
  });
});
