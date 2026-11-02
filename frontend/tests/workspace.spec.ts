import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const VIEW_EMPTY = { workspace: null, csrf: "c1", version: 0, retention_hours: null, expires_at: null, report: null };
const VIEW_WS = {
  ...VIEW_EMPTY,
  version: 3,
  workspace: { generation_id: "g1", version: 3, company_name: "星軌示範商店", industry: "general", modules: ["crm"] },
};

function routeFetch(table: Record<string, () => Response>) {
  const seen: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      seen.push(`${init?.method ?? "GET"} ${url}`);
      const handler = table[`${init?.method ?? "GET"} ${url}`];
      if (!handler) return json(404, { error: { code: "not_found", message: "找不到資源" } });
      return handler();
    }),
  );
  return seen;
}

async function freshStore() {
  const { useWorkspaceStore } = await import("../src/stores/workspace");
  return useWorkspaceStore();
}

describe("workspace store", () => {
  beforeEach(() => {
    vi.resetModules();
    setActivePinia(createPinia());
    window.sessionStorage.clear();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("refresh treats 404 endpoints as not available", async () => {
    const seen = routeFetch({ "GET /api/v1/workspace/view": () => json(200, VIEW_WS) });
    const store = await freshStore();
    await store.refresh();
    expect(seen).toEqual(
      expect.arrayContaining(["GET /api/v1/workspace/view", "GET /api/templates", "GET /api/v1/workbench"]),
    );
    expect(store.view?.workspace?.company_name).toBe("星軌示範商店");
    expect(store.templates).toBeNull();
    expect(store.workbench).toBeNull();
    expect(store.error).toBe("");
    expect(store.hasWorkspace).toBe(true);
  });

  it("refresh survives the view endpoint missing too", async () => {
    routeFetch({});
    const store = await freshStore();
    await store.refresh();
    expect(store.view).toBeNull();
    expect(store.hasWorkspace).toBe(false);
    expect(store.error).toBe("");
  });

  it("refresh reports non-404 failures", async () => {
    routeFetch({
      "GET /api/v1/workspace/view": () => json(500, { error: { code: "internal_error", message: "伺服器發生錯誤" } }),
    });
    const store = await freshStore();
    await store.refresh();
    expect(store.error).toBe("伺服器發生錯誤");
  });

  it("a workbench failure still applies the view and session", async () => {
    let bumped = false;
    const seen = routeFetch({
      "GET /api/v1/workspace/view": () => json(200, bumped ? { ...VIEW_WS, version: 4, csrf: "c2" } : VIEW_WS),
      "GET /api/v1/workbench": () => json(500, { error: { code: "internal_error", message: "伺服器發生錯誤" } }),
      "POST /api/v1/crm/customers": () => ((bumped = true), json(200, { result: "c1" })),
    });
    const store = await freshStore();
    await store.refresh();
    expect(store.view?.version).toBe(3);
    expect(store.workbench).toBeNull();
    expect(store.error).toBe("伺服器發生錯誤");
    await store.run("POST", "/api/v1/crm/customers", { name: "甲" });
    expect(store.view?.version).toBe(4);
    const { getSession } = await import("../src/api/client");
    expect(getSession()).toEqual({ csrf: "c2", version: 4 });
    expect(seen).toContain("POST /api/v1/crm/customers");
  });

  it("first load without a workspace skips workbench and allows setup", async () => {
    const seen = routeFetch({
      "GET /api/v1/workspace/view": () => json(200, VIEW_EMPTY),
      "GET /api/templates": () => json(500, { error: { code: "internal_error", message: "範本讀取失敗" } }),
      "POST /api/v1/workspace/setup": () => json(200, { result: "g1" }),
    });
    const store = await freshStore();
    await store.ready();
    expect(seen).not.toContain("GET /api/v1/workbench");
    expect(store.view?.csrf).toBe("c1");
    const out = await store.run("POST", "/api/v1/workspace/setup", { industry: "general", company_name: "甲" });
    expect(out).toEqual({ result: "g1" });
    const post = (fetch as unknown as { mock: { calls: [string, RequestInit][] } }).mock.calls.find(
      ([u]) => u === "/api/v1/workspace/setup",
    )!;
    expect(new Headers(post[1].headers).get("x-csrf-token")).toBe("c1");
  });

  it("run refreshes after success and shows a message", async () => {
    let views = 0;
    routeFetch({
      "GET /api/v1/workspace/view": () => (views++, json(200, VIEW_WS)),
      "POST /api/v1/crm/customers": () => json(200, { result: "c1" }),
    });
    const store = await freshStore();
    await store.refresh();
    const out = await store.run("POST", "/api/v1/crm/customers", { name: "甲" });
    expect(out).toEqual({ result: "c1" });
    expect(views).toBe(2);
    expect(store.message).toBe("已儲存模擬操作。");
    expect(store.busy).toBe(false);
  });

  it.each([409, 412])("run refreshes on %i", async (status) => {
    let views = 0;
    routeFetch({
      "GET /api/v1/workspace/view": () => (views++, json(200, VIEW_WS)),
      "POST /api/v1/crm/customers": () => json(status, { error: { code: "version_stale", message: "資料已更新" } }),
    });
    const store = await freshStore();
    await store.refresh();
    const out = await store.run("POST", "/api/v1/crm/customers", { name: "甲" });
    expect(out).toBeNull();
    expect(views).toBe(2);
    expect(store.error).toBe("資料已更新");
    expect(store.pending).toBeNull();
  });

  it("run keeps pending on 5xx and blocks later runs until retried", async () => {
    let fail = true;
    routeFetch({
      "GET /api/v1/workspace/view": () => json(200, VIEW_WS),
      "POST /api/v1/crm/customers": () =>
        fail ? json(503, { error: { code: "unavailable", message: "暫時無法服務" } }) : json(200, { result: "c1" }),
    });
    const store = await freshStore();
    await store.refresh();
    await store.run("POST", "/api/v1/crm/customers", { name: "甲" });
    expect(store.pending).not.toBeNull();
    expect(await store.run("POST", "/api/v1/crm/customers", { name: "乙" })).toBeNull();
    expect(store.error).toContain("上次操作的結果尚未確認");
    fail = false;
    await store.retry();
    expect(store.pending).toBeNull();
    expect(store.message).toBe("已確認並恢復原操作。");
  });

  it("run is refused while a design preview is active", async () => {
    const seen = routeFetch({ "GET /api/v1/workspace/view": () => json(200, VIEW_WS) });
    const store = await freshStore();
    await store.refresh();
    store.setDesignPreview(true);
    expect(await store.run("POST", "/api/v1/crm/customers", { name: "甲" })).toBeNull();
    expect(store.error).toBe("請先套用或取消外觀試看，再進行資料操作。");
    expect(seen.filter((s) => s.startsWith("POST"))).toHaveLength(0);
  });
});
