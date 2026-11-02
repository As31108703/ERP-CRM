import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { QueueItem, Workbench } from "../src/api/types";
import FirstRunGuide from "../src/modules/overview/FirstRunGuide.vue";
import GlobalSearch from "../src/modules/overview/GlobalSearch.vue";
import OverviewPage from "../src/modules/overview/OverviewPage.vue";
import RoleCenter from "../src/modules/overview/RoleCenter.vue";
import WorkQueue from "../src/modules/overview/WorkQueue.vue";
import { useUiStore } from "../src/stores/ui";
import { flush, workspace } from "./pageHarness";
import { json, mountOverview } from "./overviewHarness";

beforeEach(() => window.sessionStorage.clear());
afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
  window.sessionStorage.clear();
});

function queueItem(i: number, priority: "attention" | "next"): QueueItem {
  return {
    id: `order:o${i}:pay`,
    target: { module: "sales", kind: "order", id: `o${i}` },
    title: `訂單 ${i}`,
    description: `說明 ${i}`,
    priority,
    label: priority === "attention" ? "準備買家測試幣" : "支付測試幣",
  };
}

function bench(over: Partial<Workbench> = {}): Workbench {
  return {
    readiness: {},
    queue: [],
    roles: {
      owner: {
        available: true,
        cards: [
          {
            id: "open-orders",
            label: "待處理訂單",
            module: "sales",
            count: 3,
            unit: "筆",
            description: "尚有未付或未出貨品項。",
            target: { module: "sales", kind: "order", id: "o1" },
          },
          { id: "empty-stock", label: "無可用庫存商品", module: "inventory", count: 1, unit: "項", description: "可用為 0。" },
        ],
        flow: {
          id: "sales",
          title: "從備貨到接單出貨",
          steps: [
            { module: "inventory", label: "準備商品與庫存" },
            { module: "reports", label: "核對模擬報表" },
          ],
        },
      },
      sales: { available: true, cards: [], flow: null },
      operations: {
        available: true,
        cards: [{ id: "open-work-orders", label: "進行中工單", module: "manufacturing", count: 2, unit: "筆", description: "尚未完工。" }],
        flow: { title: "從材料到完工", steps: ["inventory", "manufacturing", "reports"] },
      },
      administration: { available: false, cards: [], flow: null },
    },
    ...over,
  };
}

describe("work queue", () => {
  it("filters, caps at eight and navigates to the target", async () => {
    const queue = [0, 1, 2].map((i) => queueItem(i, "attention")).concat([3, 4, 5, 6, 7, 8, 9].map((i) => queueItem(i, "next")));
    const { wrapper, router } = await mountOverview(WorkQueue, workspace(), { workbench: bench({ queue }) });
    expect(wrapper.get("[data-testid=work-queue-count]").text()).toBe("10 件");
    expect(wrapper.findAll("[data-testid=work-queue-item]")).toHaveLength(8);
    const more = wrapper.get("[data-testid=work-queue-more]");
    expect(more.text()).toBe("查看其餘 2 件工作");
    await more.trigger("click");
    expect(wrapper.findAll("[data-testid=work-queue-item]")).toHaveLength(10);
    expect(wrapper.get("[data-testid=work-queue-more]").text()).toBe("收合待處理工作");

    const attention = wrapper.get("[data-testid=work-queue-filter-attention]");
    expect(attention.text()).toContain("3");
    await attention.trigger("click");
    expect(attention.attributes("aria-pressed")).toBe("true");
    expect(wrapper.findAll("[data-testid=work-queue-item]")).toHaveLength(3);
    expect(wrapper.find("[data-testid=work-queue-more]").exists()).toBe(false);

    await wrapper.findAll("[data-testid=work-queue-item]")[1].trigger("click");
    await flush();
    expect(router.currentRoute.value.path).toBe("/m/sales");
    expect(router.currentRoute.value.query.target).toBe("order:o1");
  });

  it("shows a per-filter empty text", async () => {
    const { wrapper } = await mountOverview(WorkQueue, workspace(), { workbench: bench({ queue: [queueItem(1, "attention")] }) });
    await wrapper.get("[data-testid=work-queue-filter-next]").trigger("click");
    expect(wrapper.get("[data-testid=work-queue-empty]").text()).toContain("沒有可直接接續");
    await wrapper.get("[data-testid=work-queue-filter-all]").trigger("click");
    expect(wrapper.find("[data-testid=work-queue-empty]").exists()).toBe(false);
  });
});

describe("role center", () => {
  it("disables unavailable views, persists the choice and navigates", async () => {
    const { wrapper, router } = await mountOverview(RoleCenter, workspace(), { workbench: bench() });
    const admin = wrapper.get("[data-testid=role-view-administration]");
    expect(admin.attributes("disabled")).toBeDefined();
    expect(admin.text()).toContain("需啟用相關功能");
    expect(wrapper.get("[data-testid=role-view-owner]").attributes("aria-pressed")).toBe("true");

    const card = wrapper.get("[data-testid=role-card-open-orders]");
    expect(card.text()).toContain("待處理訂單");
    expect(card.text()).toContain("3");
    expect(card.text()).toContain("筆");
    await card.trigger("click");
    await flush();
    expect(router.currentRoute.value.fullPath).toBe("/m/sales?target=order:o1");

    await wrapper.get("[data-testid=role-card-empty-stock]").trigger("click");
    await flush();
    expect(router.currentRoute.value.fullPath).toBe("/m/inventory");

    await wrapper.get("[data-testid=role-flow-step-reports]").trigger("click");
    await flush();
    expect(router.currentRoute.value.path).toBe("/reports");

    await wrapper.get("[data-testid=role-view-operations]").trigger("click");
    expect(JSON.parse(window.sessionStorage.getItem("erpcrm.role-view.v1.gen-1") ?? "null")).toEqual({
      version: 1,
      view: "operations",
    });
    expect(wrapper.get("[data-testid=role-card-open-work-orders]").text()).toContain("進行中工單");
    expect(wrapper.text()).toContain("從材料到完工");
    expect(wrapper.get("[data-testid=role-flow-step-manufacturing]").text()).toContain("BOM 與製造");
  });

  it("falls back to the owner view when the stored view is unavailable", async () => {
    window.sessionStorage.setItem("erpcrm.role-view.v1.gen-1", JSON.stringify({ version: 1, view: "administration" }));
    const { wrapper } = await mountOverview(RoleCenter, workspace(), { workbench: bench() });
    expect(wrapper.get("[data-testid=role-view-owner]").attributes("aria-pressed")).toBe("true");
  });
});

describe("first-run guide", () => {
  const FIRST_RUN = {
    progress: [
      { id: "workspace", label: "工作區已建立", done: true },
      { id: "records", label: "新增或調整資料", done: true },
      { id: "operation", label: "完成模擬操作", done: false },
    ],
    route: { module: "inventory", title: "整理你的商品", description: "查看示範商品。", action: "查看我的商品" },
    learning_available: 2,
  };

  it("renders server progress, navigates and remembers the collapsed state", async () => {
    const fetchMock = vi.fn(async (_url: string) => json(200, FIRST_RUN));
    vi.stubGlobal("fetch", fetchMock);
    const { wrapper, router } = await mountOverview(FirstRunGuide, workspace());
    await vi.waitFor(() => expect(wrapper.find("[data-testid=first-run-start]").exists()).toBe(true));
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/workbench/first-run");
    expect(wrapper.text()).toContain("2／3");
    expect(wrapper.get("[data-testid=first-run-item-operation]").text()).toContain("完成模擬操作");
    expect(wrapper.get("[data-testid=first-run-item-operation]").attributes("data-done")).toBe("false");

    await wrapper.get("[data-testid=first-run-start]").trigger("click");
    await flush();
    expect(router.currentRoute.value.path).toBe("/m/inventory");
    await wrapper.get("[data-testid=first-run-learning]").trigger("click");
    await flush();
    expect(router.currentRoute.value.path).toBe("/learning");

    await wrapper.get("[data-testid=first-run-hide]").trigger("click");
    expect(wrapper.find("[data-testid=first-run-guide]").exists()).toBe(false);
    expect(JSON.parse(window.sessionStorage.getItem("erpcrm.first-run.v1.gen-1") ?? "null")).toEqual({
      version: 1,
      hidden: true,
    });
    await wrapper.get("[data-testid=first-run-reopen]").trigger("click");
    expect(wrapper.find("[data-testid=first-run-guide]").exists()).toBe(true);
  });

  it("starts collapsed when stored hidden for this generation", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json(200, FIRST_RUN)));
    window.sessionStorage.setItem("erpcrm.first-run.v1.gen-1", JSON.stringify({ version: 1, hidden: true }));
    const { wrapper } = await mountOverview(FirstRunGuide, workspace());
    expect(wrapper.find("[data-testid=first-run-guide]").exists()).toBe(false);
    expect(wrapper.get("[data-testid=first-run-reopen]").text()).toContain("開啟上手引導");
  });
});

describe("first-run learning entry", () => {
  it("hides the learning entry when no learning path is available", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json(200, { progress: [], route: null, learning_available: 0 })));
    const { wrapper } = await mountOverview(FirstRunGuide, workspace());
    await flush();
    expect(wrapper.find("[data-testid=first-run-learning]").exists()).toBe(false);
  });
});

describe("global search", () => {
  function item(i: number, module = "sales") {
    return { module, kind: module === "sales" ? "order" : "customer", id: `r${i}`, title: `紀錄 ${i}`, description: "說明", status_label: i === 0 ? null : "待付款" };
  }

  it("queries the server, groups by module, loads more and navigates", async () => {
    const fetchMock = vi.fn(async (url: string) => {
      const offset = Number(new URL(url, "http://x").searchParams.get("offset"));
      const items = offset === 0 ? [item(0, "crm"), ...Array.from({ length: 49 }, (_, i) => item(i + 1))] : [item(50)];
      return json(200, { total: 51, items });
    });
    vi.stubGlobal("fetch", fetchMock);
    const { wrapper, router } = await mountOverview(GlobalSearch, workspace());
    useUiStore().openSearch();
    await flush();
    const input = wrapper.get("[data-testid=search-input]");
    expect(input.attributes("maxlength")).toBe("120");
    expect(wrapper.text()).toContain("輸入關鍵字");
    await input.setValue("ＤＥＭＯ　００１");
    await vi.waitFor(() => expect(wrapper.find("[data-testid=search-count]").exists()).toBe(true));
    expect(fetchMock.mock.calls[0][0]).toBe(
      `/api/v1/workbench/search?q=${encodeURIComponent("ＤＥＭＯ　００１")}&offset=0&limit=50`,
    );
    expect(wrapper.get("[data-testid=search-count]").text()).toContain("50／51");
    const groups = wrapper.findAll("[data-testid=search-group]").map((g) => g.get("h3").text());
    expect(groups).toEqual(["客戶與商機", "模擬訂單"]);
    expect(wrapper.findAll("[data-testid=search-result]")[0].text()).toContain("查看紀錄");

    await wrapper.get("[data-testid=search-more]").trigger("click");
    await vi.waitFor(() => expect(wrapper.get("[data-testid=search-count]").text()).toContain("51／51"));
    expect(fetchMock.mock.calls[1][0]).toContain("offset=50");
    expect(wrapper.find("[data-testid=search-more]").exists()).toBe(false);

    await wrapper.findAll("[data-testid=search-result]")[0].trigger("click");
    await flush();
    expect(router.currentRoute.value.fullPath).toBe("/m/crm?target=customer:r0");
    expect(useUiStore().searchOpen).toBe(false);
  });

  it("shows the no-match text", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json(200, { total: 0, items: [] })));
    const { wrapper } = await mountOverview(GlobalSearch, workspace());
    useUiStore().openSearch();
    await flush();
    await wrapper.get("[data-testid=search-input]").setValue("無此紀錄");
    await vi.waitFor(() => expect(wrapper.find("[data-testid=search-empty]").exists()).toBe(true));
    expect(wrapper.get("[data-testid=search-empty]").text()).toContain("沒有找到");
  });

  it("Ctrl/Cmd+K opens search except in inputs, open dialogs or without a workspace", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json(200, { total: 0, items: [] })));
    const { store } = await mountOverview(GlobalSearch, workspace());
    const ui = useUiStore();
    const press = (target: EventTarget, meta = false) =>
      target.dispatchEvent(new KeyboardEvent("keydown", { key: "k", ctrlKey: !meta, metaKey: meta, bubbles: true, cancelable: true }));

    const field = document.createElement("input");
    document.body.appendChild(field);
    press(field);
    expect(ui.searchOpen).toBe(false);

    const dialog = document.createElement("div");
    dialog.setAttribute("data-erpcrm-dialog", "");
    document.body.appendChild(dialog);
    press(document.body);
    expect(ui.searchOpen).toBe(false);
    dialog.remove();

    press(document.body, true);
    expect(ui.searchOpen).toBe(true);
    ui.closeSearch();

    store.view = { workspace: null, csrf: "c", version: 0 };
    press(document.body);
    expect(ui.searchOpen).toBe(false);
  });
});

describe("overview page", () => {
  it("shows heading, metrics, modules and template panel", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json(404, { error: { code: "not_found", message: "找不到資源" } })));
    const ws = workspace({
      customers: [{ id: "c1", name: "甲" }],
      orders: [{ id: "o1", status: "pending", lines: [] }],
    });
    const { wrapper, store } = await mountOverview(OverviewPage, ws, { workbench: bench() });
    store.templates = {
      items: [{ id: "general", name: "一般零售", purpose: "", modules: [], version: 1 }],
      defaults: { industry: "general", company_name: "", public_demo: false, retention_hours: null },
    };
    store.view = { ...store.view!, report: { inventory_value_minor: 12345, gross_profit_minor: 500 } };
    await flush();
    expect(wrapper.get("h1").text()).toBe("星軌示範商店");
    expect(wrapper.text()).toContain("一般零售範本 · 已啟用 5 個模組");
    expect(wrapper.text()).toContain("SIM 獨立工作區");
    expect(wrapper.get("[data-testid=metric-customers]").text()).toContain("1");
    expect(wrapper.get("[data-testid=metric-inventory]").text()).toContain("123.45");
    expect(wrapper.findAll("[data-testid=module-tile]")).toHaveLength(5);
    expect(wrapper.text()).toContain("自架工作區 · 無自動清除期限");
    for (const id of ["role-center", "pinned-records", "work-queue"]) {
      expect(wrapper.find(`[data-testid=${id}]`).exists()).toBe(true);
    }
  });
});

describe("dialog focus", () => {
  it("search focuses the query input when opened", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json(200, { total: 0, items: [] })));
    await mountOverview(GlobalSearch, workspace());
    useUiStore().openSearch();
    await flush();
    expect(document.activeElement?.getAttribute("data-testid")).toBe("search-input");
  });
});
