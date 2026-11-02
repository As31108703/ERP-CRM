import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import LearningStudio from "../src/modules/learning/LearningStudio.vue";
import { setSession } from "../src/api/client";
import { useWorkspaceStore } from "../src/stores/workspace";
import { json } from "./overviewHarness";
import { flush, workspace } from "./pageHarness";

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

const STEP_IDS = ["customer", "buyer", "fund-business", "receive", "fund-buyer", "order", "pay", "ship"];
const NODES: Record<string, string> = {
  customer: "customer",
  buyer: "wallet",
  "fund-business": "wallet",
  receive: "inventory",
  "fund-buyer": "wallet",
  order: "order",
  pay: "order",
  ship: "shipment",
};

function pathDef() {
  return {
    id: "sales",
    title: "把第一筆訂單送出去",
    subtitle: "從顧客到出貨，練習一筆完整的模擬交易。",
    modules: ["crm", "wallets", "inventory", "sales"],
    headline: "把一筆訂單，走到出貨。",
    intro: "先備好商品和測試幣。",
    outcome: "你會看見：付款不會移動庫存。",
    nodes: ["wallet", "inventory", "order", "shipment"],
    steps: STEP_IDS.map((id, i) => ({
      id,
      action: "customer.create",
      title: `步驟標題 ${i + 1}`,
      body: `步驟說明 ${i + 1}`,
      change: `改變 ${i + 1}`,
      nav: "crm",
      node: NODES[id],
    })),
    quiz: { question: "問題？", choices: ["甲", "乙", "丙"], answer: 1, explanation: "說明。" },
  };
}

/** 前兩步已完成、下一步是第三步（index 2）的 detail。 */
function detail(view: { paused?: boolean; selected_step?: string | null } = {}) {
  return {
    path: pathDef(),
    session: {
      id: "s1",
      path: "sales",
      run_id: "run-0001-abcd",
      active: true,
      paused: view.paused ?? false,
      scope: "lesson",
      compact: false,
      quiz_choice: null,
      selected_step: view.selected_step ?? null,
      created_at: "2026-11-02T00:00:00.000Z",
      updated_at: "2026-11-02T00:00:00.000Z",
    },
    evaluation: {
      steps: STEP_IDS.map((id, i) => ({
        id,
        complete: i < 2,
        evidence_text: i < 2 ? `已完成 ${id}` : "尚無本次操作證據。",
        checkpoint: i < 2 ? { action: "customer.create", payload: {}, result: `r-${id}`, version: 3 + i } : null,
      })),
      next_index: 2,
      complete: false,
    },
    preview: { text: "商家錢包增加 100.00 SIM，留下補幣流水。", blocked_reason: null },
    facts: {
      lesson: [
        { label: "本輪顧客", value: "1 位", node: null },
        { label: "本輪訂單", value: "0 筆", node: "order" },
        { label: "本輪已出貨", value: "0 件", node: "shipment" },
        { label: "共用商品現有量 · 星塵咖啡豆", value: "5 件", node: "inventory" },
        { label: "本輪買家測試幣", value: "0.00 SIM", node: "wallet" },
      ],
      workspace: [
        { label: "工作區顧客", value: "4 位", node: null },
        { label: "工作區已出貨", value: "3 件", node: "shipment" },
      ],
    },
    snapshots: {},
  };
}

async function mountStudio(body: ReturnType<typeof detail>) {
  const fetchMock = vi.fn(async (url: string) => {
    if (url === "/api/v1/learning") {
      return json(200, {
        available_paths: ["sales"],
        sessions: [{ path: "sales", run_id: "run-0001-abcd", confirmed: 2, total: 8 }],
        active: "sales",
      });
    }
    if (url === "/api/v1/learning/sales") return json(200, body);
    return json(404, { error: { code: "not_found", message: "找不到資源" } });
  });
  vi.stubGlobal("fetch", fetchMock);

  setActivePinia(createPinia());
  const store = useWorkspaceStore();
  const ws = workspace({ modules: ["crm", "wallets", "inventory", "sales"] });
  store.view = { workspace: ws, csrf: "c", version: ws.version };
  store.loaded = true;
  setSession({ csrf: "c", version: ws.version });

  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/:rest(.*)*", component: { render: () => null } }],
  });
  await router.push("/learning");
  await router.isReady();
  const wrapper = mount(LearningStudio, { global: { plugins: [router] }, attachTo: document.body });
  await vi.waitFor(() => expect(wrapper.find("[data-testid=learning-execute]").exists()).toBe(true));
  await flush();
  return { wrapper, fetchMock, store };
}

function executeDisabled(wrapper: Awaited<ReturnType<typeof mountStudio>>["wrapper"]): boolean {
  return wrapper.get("[data-testid=learning-execute]").attributes("disabled") !== undefined;
}

describe("learning studio", () => {
  it("execute button disabled when reading ahead", async () => {
    const current = await mountStudio(detail());
    expect(executeDisabled(current.wrapper)).toBe(false);
    current.wrapper.unmount();

    const { wrapper } = await mountStudio(detail({ selected_step: "pay" }));
    expect(wrapper.get("[data-testid=learning-scene]").text()).toContain("步驟標題 7");
    expect(wrapper.get("[data-testid=learning-scene]").text()).toContain("閱讀預覽");
    expect(executeDisabled(wrapper)).toBe(true);
    expect(wrapper.find("[data-testid=learning-back-to-current]").exists()).toBe(true);
  });

  it("paused disables execute", async () => {
    const { wrapper, fetchMock } = await mountStudio(detail({ paused: true }));
    expect(wrapper.get("[data-testid=learning-scene]").text()).toContain("已暫停");
    expect(executeDisabled(wrapper)).toBe(true);
    expect(wrapper.get("[data-testid=learning-diagram]").classes()).toContain("is-still");

    await wrapper.get("[data-testid=learning-execute]").trigger("click");
    await flush();
    const posts = fetchMock.mock.calls.filter((c) => String(c[0]).endsWith("/execute"));
    expect(posts).toHaveLength(0);
  });
});

describe("learning studio commands", () => {
  it("executes the current step through the command pipeline and re-reads the detail", async () => {
    const { wrapper, fetchMock, store } = await mountStudio(detail());
    const run = vi.fn(async () => ({ result: "new-id" }));
    store.run = run as unknown as typeof store.run;
    const before = fetchMock.mock.calls.filter((c) => c[0] === "/api/v1/learning/sales").length;

    await wrapper.get("[data-testid=learning-execute]").trigger("click");
    await flush();
    expect(run).toHaveBeenCalledWith("POST", "/api/v1/learning/sales/execute", { step_id: "fund-business" });
    const after = fetchMock.mock.calls.filter((c) => c[0] === "/api/v1/learning/sales").length;
    expect(after).toBe(before + 1);
    expect(wrapper.text()).toContain("操作已確認");
  });

  it("pause is a preference write with csrf only", async () => {
    const { wrapper, fetchMock } = await mountStudio(detail());
    fetchMock.mockImplementationOnce(async () => json(200, detail({ paused: true })));
    await wrapper.get("[data-testid=learning-pause]").trigger("click");
    await flush();
    const call = fetchMock.mock.calls.find((c) => String(c[0]).endsWith("/view")) as unknown as [string, RequestInit];
    expect(call[1].method).toBe("PATCH");
    expect(JSON.parse(String(call[1].body))).toEqual({ paused: true });
    const headers = new Headers(call[1].headers);
    expect(headers.get("x-csrf-token")).toBe("c");
    expect(headers.get("Idempotency-Key")).toBeNull();
    expect(headers.get("If-Match-Version")).toBeNull();
    expect(wrapper.get("[data-testid=learning-execute]").attributes("disabled")).toBeDefined();
  });

  it("inspect locates the record created by a completed step", async () => {
    const { wrapper } = await mountStudio(detail({ selected_step: "customer" }));
    await wrapper.get("[data-testid=learning-inspect]").trigger("click");
    await flush();
    const route = (wrapper.vm.$router as ReturnType<typeof createRouter>).currentRoute.value;
    expect(route.path).toBe("/m/crm");
    expect(route.query.target).toBe("customer:r-customer");
  });

  it("shows the empty state when no path is available", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json(200, { available_paths: [], sessions: [], active: null })),
    );
    setActivePinia(createPinia());
    const store = useWorkspaceStore();
    const ws = workspace({ modules: ["crm"] });
    store.view = { workspace: ws, csrf: "c", version: ws.version };
    store.loaded = true;
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/:rest(.*)*", component: { render: () => null } }] });
    await router.push("/learning");
    const wrapper = mount(LearningStudio, { global: { plugins: [router] } });
    await vi.waitFor(() => expect(wrapper.text()).toContain("先啟用一條完整工作流程"));
    expect(wrapper.text()).toContain("查看模組設定");
    expect(wrapper.find("[data-testid=learning-execute]").exists()).toBe(false);
  });
});

describe("learning flow diagram", () => {
  it("shows each node's fact by its node key and highlights the current step's node", async () => {
    const { wrapper, fetchMock } = await mountStudio(detail());
    const node = (id: string) => wrapper.get(`[data-testid=learning-diagram] [data-node="${id}"]`);
    expect(node("shipment").text()).toContain("出貨與成本");
    expect(node("shipment").text()).toContain("本輪已出貨 0 件");
    expect(node("inventory").text()).toContain("共用商品現有量 · 星塵咖啡豆 5 件");
    expect(node("wallet").text()).toContain("本輪買家測試幣");
    // 下一步 fund-business 的節點是 wallet
    expect(node("wallet").classes()).toContain("is-current");
    expect(node("shipment").classes()).not.toContain("is-current");

    const scoped = detail();
    scoped.session.scope = "workspace";
    fetchMock.mockImplementationOnce(async () => json(200, scoped));
    await wrapper.get("[data-testid=learning-scope-workspace]").trigger("click");
    await flush();
    expect(node("shipment").text()).toContain("工作區已出貨 3 件");
    expect(node("order").text()).toContain("本輪尚無對應紀錄");
  });
});
