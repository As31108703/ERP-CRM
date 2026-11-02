import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, describe, expect, it, vi, type Mock } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import type { WorkspaceSnapshot } from "../src/api/types";
import AdminDesk from "../src/modules/administration/AdminDesk.vue";
import { currentWeek, parseCsv, printDataFromCsv, taipeiInputToIso } from "../src/modules/administration/adminModel";
import { useWorkspaceStore } from "../src/stores/workspace";
import { flush, workspace } from "./pageHarness";

const STAMP = { created_at: "2026-11-01T00:00:00+00:00", updated_at: "2026-11-01T00:00:00+00:00" };
const WEEK = currentWeek();

function admin() {
  return {
    units: [{ id: "u1", name: "星港門市", kind: "branch", parent_id: null, active: true, ...STAMP }],
    staff: [{ id: "s1", code: "S-1", alias: "星員甲", unit_id: "u1", role_label: "", status: "active", ...STAMP }],
    shifts: [
      {
        id: "sh1",
        staff_id: "s1",
        unit_id: "u1",
        start_at: `${WEEK}T09:00:00+08:00`,
        end_at: `${WEEK}T17:00:00+08:00`,
        break_minutes: 60,
        note: "早班",
        status: "scheduled",
        ...STAMP,
      },
    ],
    attendance: [],
    requests: [
      {
        id: "r1",
        type: "purchase",
        staff_id: "s1",
        unit_id: "u1",
        title: "請購星砂",
        description: "",
        amount_minor: 3200,
        currency: "SIM",
        start_at: null,
        end_at: null,
        status: "submitted",
        processing_note: "",
        transitions: [
          { status: "draft", at: STAMP.created_at, note: "" },
          { status: "submitted", at: STAMP.created_at, note: "" },
        ],
        ...STAMP,
      },
    ],
    equipment: [],
    reservations: [],
    notices: [],
    changes: [],
  };
}

const OVERVIEW = {
  now: new Date().toISOString(),
  week: WEEK,
  tiles: [
    {
      id: "requests",
      label: "申請待整理",
      value: 1,
      unit: "件",
      sub: "0 件待補件",
      target: { tab: "requests", unit: null, type: "all", status: "submitted" },
    },
  ],
  onboarding: {
    steps: [
      { id: "unit", label: "建立組織", detail: "", done: true, reason: "", button: "再建立組織" },
      { id: "staff", label: "加入假員工", detail: "", done: true, reason: "", button: "再加入假員工" },
      { id: "shift", label: "排第一個班次", detail: "", done: true, reason: "", button: "新增另一個班次" },
    ],
    completed: 3,
    open: false,
    summary: "已完成 3／3 步",
  },
  demo_empty: false,
  counts: {},
};

const CSV =
  "﻿" +
  [
    ["模式", "工作區", "工作區版本", "資料類型", "組織範圍", "搜尋條件", "狀態篩選", "日期範圍", "時區", "產出時間", "篩選統計", "資料來源", "紀錄編號", "標題"],
    ["SIM 流程練習", "星軌示範商店", "7", "申請", "全部組織", "未設定", "全部", "全部日期", "Asia/Taipei", "2026-11-02", "共 1 筆", "SIM", "r1", "'=HYPERLINK(\"x\")"],
  ]
    .map((r) => r.map((c) => `"${c.replace(/"/g, '""')}"`).join(","))
    .join("\r\n") +
  "\r\n";

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

interface Mounted {
  wrapper: ReturnType<typeof mount>;
  run: Mock;
  fetchMock: Mock;
  router: ReturnType<typeof createRouter>;
  store: ReturnType<typeof useWorkspaceStore>;
}

async function mountDesk(ws: WorkspaceSnapshot, path = "/administration"): Promise<Mounted> {
  const data = (ws.administration ?? null) as Record<string, unknown[]> | null;
  const fetchMock = vi.fn(async (input: string) => {
    const url = new URL(input, "http://x");
    if (url.pathname.endsWith("/rows")) {
      const tab = url.searchParams.get("tab") ?? "";
      return json(200, { rows: data?.[tab] ?? [], summary: `共 ${(data?.[tab] ?? []).length} 筆`, status_scope: "全部", period: "全部日期" });
    }
    if (url.pathname.endsWith("/overview")) return json(200, OVERVIEW);
    if (url.pathname.endsWith("/attendance-diff")) return json(200, []);
    if (url.pathname.endsWith("/export.csv")) return new Response(CSV, { status: 200, headers: { "Content-Type": "text/csv" } });
    return json(404, { error: { code: "not_found", message: "找不到資源" } });
  });
  vi.stubGlobal("fetch", fetchMock);

  setActivePinia(createPinia());
  const store = useWorkspaceStore();
  store.view = { workspace: ws, csrf: "c", version: ws.version };
  store.loaded = true;
  const run: Mock = vi.fn(async () => ({ result: "new-id" }));
  store.run = run as unknown as typeof store.run;

  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/administration", name: "administration", component: AdminDesk },
      { path: "/:rest(.*)*", component: { render: () => null } },
    ],
  });
  await router.push(path);
  await router.isReady();
  const wrapper = mount(AdminDesk, { global: { plugins: [router], stubs: { teleport: true } }, attachTo: document.body });
  await flush();
  return { wrapper, run, fetchMock, router, store };
}

function enabledWs() {
  return workspace({ modules: ["administration"], administration: admin() });
}

function lastRowsUrl(fetchMock: Mock): URL {
  const calls = fetchMock.mock.calls.map((c) => new URL(String(c[0]), "http://x")).filter((u) => u.pathname.endsWith("/rows"));
  return calls[calls.length - 1];
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

describe("AdminDesk", () => {
  it("shows the enable panel and sends office.enable after confirmation", async () => {
    const { wrapper, run } = await mountDesk(workspace({ modules: ["sales"] }));
    expect(wrapper.find("[data-testid=admin-enable-panel]").exists()).toBe(true);
    expect(wrapper.find("[data-testid=admin-tabs]").exists()).toBe(false);
    await wrapper.get("[data-testid=admin-enable]").trigger("click");
    await wrapper.get("[data-testid=admin-form]").trigger("submit");
    await flush();
    expect(run).toHaveBeenCalledWith("POST", "/api/v1/administration/enable", {});
  });

  it("switches tabs with arrow, Home and End keys and refetches rows", async () => {
    const { wrapper, fetchMock } = await mountDesk(enabledWs());
    const tabs = wrapper.get("[data-testid=admin-tabs]");
    expect(wrapper.get("[aria-selected=true]").attributes("data-tab")).toBe("shifts");
    expect(lastRowsUrl(fetchMock).searchParams.get("tab")).toBe("shifts");

    await tabs.trigger("keydown", { key: "ArrowRight" });
    await flush();
    expect(wrapper.get("[aria-selected=true]").attributes("data-tab")).toBe("attendance");
    expect(lastRowsUrl(fetchMock).searchParams.get("status")).toBe("active");
    expect(wrapper.find("[data-testid=attendance-diff]").exists()).toBe(true);

    await tabs.trigger("keydown", { key: "End" });
    await flush();
    expect(wrapper.get("[aria-selected=true]").attributes("data-tab")).toBe("notices");

    await tabs.trigger("keydown", { key: "ArrowRight" });
    await flush();
    expect(wrapper.get("[aria-selected=true]").attributes("data-tab")).toBe("units");

    await tabs.trigger("keydown", { key: "Home" });
    await flush();
    expect(wrapper.get("[aria-selected=true]").attributes("data-tab")).toBe("units");

    // 每個分頁都顯示筆數。
    expect(wrapper.get("[data-tab=requests] .atabs__count").text()).toBe("1");
  });

  it("renders the 7-day shift grid with the week label and card actions", async () => {
    const { wrapper } = await mountDesk(enabledWs());
    const days = wrapper.findAll("[data-testid=shift-grid] > li");
    expect(days).toHaveLength(7);
    expect(days[0].text()).toContain("星期一");
    expect(days[0].text()).toContain("1 班");
    expect(wrapper.get("[data-testid=admin-week-label]").text()).toContain(WEEK);
    const card = wrapper.get('[data-record-id="sh1"]');
    expect(card.text()).toContain("09:00–17:00");
    expect(card.text()).toContain("淨 420 分");
    expect(card.findAll("button").map((b) => b.text())).toEqual(["編輯班次時段", "結束班次", "取消班次"]);
  });

  it("focuses ?target=request:<id> and shows the lifecycle track", async () => {
    const { wrapper, fetchMock, router } = await mountDesk(enabledWs(), "/administration?target=request:r1");
    expect(wrapper.get("[aria-selected=true]").attributes("data-tab")).toBe("requests");
    const url = lastRowsUrl(fetchMock);
    expect(url.searchParams.get("status")).toBe("all");
    const card = wrapper.get('[data-record-id="r1"]');
    expect(card.classes()).toContain("is-target");
    expect(card.find(".ltrack").exists()).toBe(true);
    expect(card.findAll("button").map((b) => b.text())).toEqual(["退回補件", "整理完成（未覆核）", "撤回申請"]);

    // 「清除定位」移除 target 後取消醒目標示。
    await router.replace({ path: "/administration" });
    await flush();
    expect(wrapper.get('[data-record-id="r1"]').classes()).not.toContain("is-target");
  });

  it("overview tile applies its preset filters", async () => {
    const { wrapper, fetchMock } = await mountDesk(enabledWs());
    await wrapper.get("[data-tile=requests]").trigger("click");
    await flush();
    const url = lastRowsUrl(fetchMock);
    expect(url.searchParams.get("tab")).toBe("requests");
    expect(url.searchParams.get("status")).toBe("submitted");
  });

  it("client preflight blocks a >48h shift; a valid save focuses the new record", async () => {
    const { wrapper, run, store } = await mountDesk(enabledWs());
    await wrapper.get("[data-testid=admin-create]").trigger("click");
    const form = wrapper.get("[data-testid=admin-form]");
    await form.get("input[name=end_at]").setValue(`${WEEK}T09:00`);
    await form.get("input[name=start_at]").setValue(`${WEEK}T08:00`);
    await form.get("input[name=end_at]").setValue("2099-01-01T00:00");
    await form.trigger("submit");
    await flush();
    expect(run).not.toHaveBeenCalled();
    expect(wrapper.get("[data-testid=form-error]").text()).toContain("48 小時");

    await form.get("input[name=end_at]").setValue(`${WEEK}T12:00`);
    await form.trigger("submit");
    await flush();
    expect(run).toHaveBeenCalledWith("POST", "/api/v1/administration/shifts", {
      staff_id: "s1",
      unit_id: "u1",
      start_at: taipeiInputToIso(`${WEEK}T08:00`),
      end_at: taipeiInputToIso(`${WEEK}T12:00`),
      break_minutes: 0,
      note: "",
    });
    expect(store.message).toBe(`已儲存「星員甲 ${WEEK} 班次」。`);
    expect(wrapper.find("[data-testid=admin-form]").exists()).toBe(false);
  });

  it("exports through the shared download helper and prints from the CSV", async () => {
    const { wrapper, fetchMock } = await mountDesk(enabledWs());
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:x"), revokeObjectURL: vi.fn() }));
    await wrapper.get("[data-testid=admin-export]").trigger("click");
    await flush();
    const exportCall = fetchMock.mock.calls.map((c) => String(c[0])).find((u) => u.includes("/export.csv"));
    expect(exportCall).toContain("tab=shifts");
    expect(click).toHaveBeenCalled();
    const anchor = click.mock.contexts[0] as HTMLAnchorElement;
    expect(anchor.download).toMatch(/^erpcrm-admin-shifts-\d{4}-\d{2}-\d{2}\.csv$/);

    const print = vi.fn();
    vi.stubGlobal("print", print);
    window.print = print;
    await wrapper.get("[data-testid=admin-print]").trigger("click");
    await flush();
    expect(print).toHaveBeenCalled();
    const sheet = wrapper.get("[data-testid=print-sheet]");
    expect(sheet.text()).toContain("SIM 行政紀錄：週班表");
    expect(sheet.findAll("dt")).toHaveLength(12);
  });
});

describe("admin CSV for print", () => {
  it("parses quoted cells, strips the BOM and the formula guard", () => {
    const rows = parseCsv(CSV);
    expect(rows[0][0]).toBe("模式");
    const data = printDataFromCsv("requests", CSV)!;
    expect(data.scope).toHaveLength(12);
    expect(data.headers).toEqual(["紀錄編號", "標題"]);
    expect(data.rows[0]).toEqual(["r1", '=HYPERLINK("x")']);
  });
});
