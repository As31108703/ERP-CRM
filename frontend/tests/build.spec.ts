import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { createMemoryHistory } from "vue-router";

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const DEPS = { sales: ["inventory", "wallets"], services: ["crm", "wallets"], manufacturing: ["inventory", "wallets"] };
const tpl = (id: string, name: string, modules: string[]) => ({
  id,
  name,
  purpose: `${name}用途`,
  modules,
  version: 1,
  terminology: { customer: "客戶", product: "商品", work_order: "工單" },
  module_dependencies: DEPS,
  default_config: { currency: "SIM" },
});
const TEMPLATES = {
  items: [
    tpl("retail", "零售商店", ["inventory", "sales", "wallets", "crm"]),
    tpl("service", "服務工作室", ["services", "wallets", "crm", "projects"]),
  ],
  defaults: { industry: "retail", company_name: "星軌示範商店", modules: null, public_demo: true, auto_setup: false, retention_hours: 72 },
};
const VIEW_EMPTY = { workspace: null, csrf: "c1", version: 0, retention_hours: 72, expires_at: null, report: null };
const VIEW_WS = {
  ...VIEW_EMPTY,
  version: 1,
  workspace: { generation_id: "g", version: 1, company_name: "甲店", industry: "service", modules: ["services", "wallets", "crm", "projects"] },
};

const KIT_URL =
  "/api/v1/backup/launch-kit?industry=service&company_name=%E7%94%B2%E5%BA%97&modules=inventory,sales,wallets,crm,projects";
let kitResponse: Response | null = null;

/** 攔下暫時的 `<a download>` 點擊與物件網址，回傳被存檔的檔名清單。 */
function stubDownload(): string[] {
  const saved: string[] = [];
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:kit"), revokeObjectURL: vi.fn() }));
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    saved.push(this.download);
  });
  return saved;
}

function stubApi() {
  const calls: { method: string; url: string; body: unknown }[] = [];
  let created = false;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      calls.push({ method, url, body: init?.body ? JSON.parse(String(init.body)) : null });
      if (url === "/api/templates") return json(200, TEMPLATES);
      if (url === "/api/v1/workspace/view") return json(200, created ? VIEW_WS : VIEW_EMPTY);
      if (url.startsWith("/api/v1/backup/launch-kit?")) return kitResponse ?? new Response(new Blob(["PK"]), { status: 200 });
      if (method === "POST" && url === "/api/v1/workspace/setup") {
        created = true;
        return json(200, { result: null, ...VIEW_WS });
      }
      return json(404, { error: { code: "not_found", message: "找不到資源" } });
    }),
  );
  return calls;
}

async function mountAt(path: string) {
  const { createAppRouter } = await import("../src/router");
  const router = createAppRouter(createMemoryHistory());
  await router.push(path);
  await router.isReady();
  const { RouterView } = await import("vue-router");
  const wrapper = mount(RouterView, { global: { plugins: [router] }, attachTo: document.body });
  await flushPromises();
  return { wrapper, router };
}

describe("build wizard", () => {
  beforeEach(() => {
    vi.resetModules();
    setActivePinia(createPinia());
    window.sessionStorage.clear();
    document.body.innerHTML = "";
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    kitResponse = null;
  });

  it("launch kit 422 is shown as an error, not saved as a zip", async () => {
    stubApi();
    const saved = stubDownload();
    kitResponse = json(422, { error: { code: "config_invalid", message: "模組設定不正確。" } });
    const { wrapper } = await mountAt("/build");
    await wrapper.get("[data-testid=company-input]").setValue("甲店");
    await wrapper.get("[data-industry=service]").trigger("click");
    await wrapper.get("[data-testid=build-next]").trigger("click");
    await wrapper.get("[data-testid=build-next]").trigger("click");
    await wrapper.get("[data-testid=dest-local]").setValue(true);
    await wrapper.get("[data-testid=launch-kit]").trigger("click");
    await flushPromises();
    expect(wrapper.findAll("[role=alert]").map((a) => a.text())).toContain("模組設定不正確。");
    expect(saved).toEqual([]);
    expect(URL.createObjectURL).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("walks three steps, cascades modules and creates the workspace", async () => {
    const calls = stubApi();
    const { wrapper, router } = await mountAt("/build");

    // 公開試用不預填名稱；沒有名稱不能前進
    const company = wrapper.get<HTMLInputElement>("[data-testid=company-input]");
    expect(company.element.value).toBe("");
    await wrapper.get("[data-testid=build-next]").trigger("click");
    expect(wrapper.get("[data-testid=step-heading]").text()).toBe("店名與行業");
    expect(wrapper.text()).toContain("請輸入店名或公司名稱。");

    await company.setValue("甲店");
    await wrapper.get("[data-industry=service]").trigger("click");
    await wrapper.get("[data-testid=build-next]").trigger("click");
    expect(wrapper.get("[data-testid=step-heading]").text()).toBe("確認推薦功能");
    expect(document.activeElement).toBe(wrapper.get("[data-testid=step-heading]").element);

    // 關閉 wallets 連帶關閉 services；草稿存到 erpcrm.builder.v1.*
    await wrapper.get("[data-module=wallets]").setValue(false);
    expect(wrapper.get("[data-testid=module-notice]").text()).toBe("一併關閉：報價與服務。");
    const key = Object.keys(window.sessionStorage).find((k) => k.startsWith("erpcrm.builder.v1."));
    expect(key).toBeTruthy();
    expect(JSON.parse(window.sessionStorage.getItem(key!)!)).toEqual({
      industry: "service",
      company: "甲店",
      modules: ["crm", "projects"],
      destination: "public",
    });
    await wrapper.get("[data-module=sales]").setValue(true);
    expect(wrapper.get("[data-testid=module-notice]").text()).toBe("一併啟用：商品庫存、測試幣流水。");

    await wrapper.get("[data-testid=build-next]").trigger("click");
    expect(wrapper.get("[data-testid=step-heading]").text()).toBe("建立我的系統");

    // 本機啟動包：先 fetch，成功才存成 ZIP
    const saved = stubDownload();
    await wrapper.get("[data-testid=dest-local]").setValue(true);
    await wrapper.get("[data-testid=launch-kit]").trigger("click");
    await flushPromises();
    expect(calls.at(-1)?.url).toBe(KIT_URL);
    expect(saved).toEqual(["erpcrm-launch-kit.zip"]);
    expect(wrapper.text()).toContain("已下載本機啟動包");

    await wrapper.find("input[value=public]").setValue(true);
    await wrapper.get("[data-testid=build-create]").trigger("click");
    await flushPromises();
    const setup = calls.filter((c) => c.method === "POST");
    expect(setup).toEqual([
      {
        method: "POST",
        url: "/api/v1/workspace/setup",
        body: { industry: "service", company_name: "甲店", modules: ["inventory", "sales", "wallets", "crm", "projects"] },
      },
    ]);
    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe("/overview"));
    wrapper.unmount();
  });

  it("restores a valid draft and ignores a tampered one", async () => {
    stubApi();
    const { draftKey } = await import("../src/modules/build/draft");
    const key = draftKey(TEMPLATES as never);
    window.sessionStorage.setItem(
      key,
      JSON.stringify({ industry: "retail", company: "乙店", modules: ["crm"], destination: "local" }),
    );
    let { wrapper } = await mountAt("/build");
    expect(wrapper.get<HTMLInputElement>("[data-testid=company-input]").element.value).toBe("乙店");
    wrapper.unmount();

    window.sessionStorage.setItem(key, JSON.stringify({ industry: "retail", company: "乙店", modules: ["sales"], destination: "local" }));
    vi.resetModules();
    setActivePinia(createPinia());
    ({ wrapper } = await mountAt("/build"));
    expect(wrapper.get<HTMLInputElement>("[data-testid=company-input]").element.value).toBe("");
    wrapper.unmount();
  });
});

describe("switch template from settings", () => {
  beforeEach(() => {
    vi.resetModules();
    setActivePinia(createPinia());
    window.sessionStorage.clear();
    document.body.innerHTML = "";
  });
  afterEach(() => vi.unstubAllGlobals());

  it("clear lands on custom setup with the chosen template, then setup succeeds", async () => {
    const calls: { method: string; url: string; body: unknown }[] = [];
    let state: "old" | "cleared" | "new" = "old";
    const OLD = { ...VIEW_WS, workspace: { ...VIEW_WS.workspace, industry: "retail", company_name: "舊店", modules: ["inventory", "sales", "wallets", "crm"] } };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? "GET";
        calls.push({ method, url, body: init?.body ? JSON.parse(String(init.body)) : null });
        if (url === "/api/templates") return json(200, TEMPLATES);
        if (url === "/api/v1/workspace/view") return json(200, state === "old" ? OLD : state === "new" ? VIEW_WS : VIEW_EMPTY);
        if (method === "POST" && url === "/api/v1/workspace/clear") {
          state = "cleared";
          return json(200, { result: null, ...VIEW_EMPTY });
        }
        if (method === "POST" && url === "/api/v1/workspace/setup") {
          state = "new";
          return json(200, { result: null, ...VIEW_WS });
        }
        return json(404, { error: { code: "not_found", message: "找不到資源" } });
      }),
    );
    const { wrapper, router } = await mountAt("/settings");
    const switchBtn = wrapper.findAll("button").find((b) => b.text() === "切換產業範本");
    await switchBtn!.trigger("click");
    await wrapper.get("[data-testid=custom-company]").setValue("乙店");
    await wrapper.get("[data-industry=service]").trigger("click");
    await wrapper.get("[data-testid=custom-create]").trigger("click");
    await flushPromises();
    expect(calls.some((c) => c.method === "POST")).toBe(false);

    const confirm = [...document.querySelectorAll<HTMLButtonElement>("[role=dialog] button")].find((b) => b.textContent?.trim() === "確認清除");
    confirm!.click();
    await flushPromises();
    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe("/custom"));
    await flushPromises();
    expect(calls.filter((c) => c.method === "POST").map((c) => c.url)).toEqual(["/api/v1/workspace/clear"]);
    expect(router.currentRoute.value.query).toEqual({ industry: "service", company: "乙店", modules: "services,wallets,crm,projects" });

    // 自訂建置頁已預選範本與名稱
    expect(wrapper.get<HTMLInputElement>("[data-testid=custom-company]").element.value).toBe("乙店");
    expect(wrapper.get("[data-industry=service]").attributes("aria-pressed")).toBe("true");
    expect(wrapper.get("[data-testid=custom-create]").text()).toBe("建立我的系統");
    await wrapper.get("[data-testid=custom-create]").trigger("click");
    await flushPromises();
    expect(calls.filter((c) => c.method === "POST").at(-1)).toEqual({
      method: "POST",
      url: "/api/v1/workspace/setup",
      body: { industry: "service", company_name: "乙店", modules: ["services", "wallets", "crm", "projects"] },
    });
    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe("/overview"));
    wrapper.unmount();
  });

  it("ignores a tampered preselection query", async () => {
    stubApi();
    const { wrapper } = await mountAt("/custom?industry=service&company=x&modules=sales");
    // sales 缺少相依模組，整份不採用，退回預設範本
    expect(wrapper.get<HTMLInputElement>("[data-testid=custom-company]").element.value).toBe("");
    expect(wrapper.get("[data-industry=retail]").attributes("aria-pressed")).toBe("true");
    wrapper.unmount();
  });
});

describe("custom setup", () => {
  beforeEach(() => {
    vi.resetModules();
    setActivePinia(createPinia());
    window.sessionStorage.clear();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("creates with the chosen template and module changes", async () => {
    const calls = stubApi();
    const { wrapper, router } = await mountAt("/custom");
    await wrapper.get("[data-testid=custom-company]").setValue(" 丙店 ");
    await wrapper.get("[data-module=administration]").setValue(true);
    await wrapper.get("[data-module=inventory]").setValue(false);
    expect(wrapper.get("[data-testid=custom-notice]").text()).toBe("一併關閉：模擬訂單。");
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(calls.filter((c) => c.method === "POST")[0]?.body).toEqual({
      industry: "retail",
      company_name: "丙店",
      modules: ["wallets", "crm", "administration"],
    });
    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe("/overview"));
    wrapper.unmount();
  });
});

describe("capability map page", () => {
  beforeEach(() => {
    vi.resetModules();
    setActivePinia(createPinia());
  });
  afterEach(() => vi.unstubAllGlobals());

  it("filters by status and search, and planned cards link to the blueprint", async () => {
    stubApi();
    const { wrapper } = await mountAt("/capabilities");
    expect(wrapper.get("[data-testid=capability-count]").text()).toBe("顯示 34／34 項功能");
    await wrapper.get("[data-status-filter=planned]").trigger("click");
    const planned = wrapper.findAll("[data-capability]").length;
    expect(wrapper.get("[data-testid=capability-count]").text()).toBe(`顯示 ${planned}／34 項功能`);
    expect(wrapper.get("[data-capability=CAP05]").text()).toContain("查看擴充藍圖");
    await wrapper.get("[data-status-filter=planned]").trigger("click");
    await wrapper.get("[data-testid=capability-search]").setValue("ＦＩＦＯ　庫存");
    expect(wrapper.findAll("[data-capability]").map((n) => n.attributes("data-capability"))).toContain("CAP17");
    expect(wrapper.get("[data-capability=CAP17]").text()).toContain("建立系統後使用");
    wrapper.unmount();
  });
});
