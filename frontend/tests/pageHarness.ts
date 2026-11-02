import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { vi, type Mock } from "vitest";
import type { Component } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import type { Workbench, WorkspaceSnapshot } from "../src/api/types";
import { useWorkspaceStore } from "../src/stores/workspace";

/** 測試用工作區：未指定的集合給空陣列。 */
export function workspace(over: Partial<WorkspaceSnapshot> = {}): WorkspaceSnapshot {
  return {
    generation_id: "gen-1",
    version: 7,
    industry: "general",
    company_name: "星軌示範商店",
    modules: ["inventory", "sales", "wallets", "services", "crm"],
    products: [],
    purchases: [],
    wallets: [],
    ledger: [],
    orders: [],
    customers: [],
    contacts: [],
    deals: [],
    cases: [],
    quotes: [],
    services: [],
    history: [],
    ...over,
  };
}

export const BASE_WALLETS = [
  { id: "w-biz", kind: "business", name: "business", balance_minor: 50000 },
  { id: "w-sup", kind: "supplier", name: "supplier", balance_minor: 0 },
  { id: "w-fau", kind: "faucet", name: "faucet", balance_minor: -60000 },
  { id: "w-buy", kind: "buyer", name: "測試買家甲", balance_minor: 10000 },
];

export interface Harness {
  wrapper: ReturnType<typeof mount>;
  run: Mock;
  store: ReturnType<typeof useWorkspaceStore>;
  router: ReturnType<typeof createRouter>;
}

/**
 * 掛載模組頁：Pinia 狀態直接寫入 view／workbench，`store.run` 換成 spy（預設回傳成功）。
 * 對話框的 Teleport 以 stub 原地渲染，方便查詢欄位。
 */
export async function mountPage(
  page: Component,
  ws: WorkspaceSnapshot,
  opts: { workbench?: Workbench | null; query?: Record<string, string>; module?: string } = {},
): Promise<Harness> {
  setActivePinia(createPinia());
  const store = useWorkspaceStore();
  store.view = { workspace: ws, csrf: "c", version: ws.version };
  store.workbench = opts.workbench ?? null;
  store.loaded = true;
  const run = vi.fn(async () => ({ result: "new-id" }));
  store.run = run as unknown as typeof store.run;

  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/m/:module", name: "module", component: page },
      { path: "/:rest(.*)*", component: { render: () => null } },
    ],
  });
  await router.push({ path: `/m/${opts.module ?? "sales"}`, query: opts.query ?? {} });
  await router.isReady();

  const wrapper = mount(page, {
    global: { plugins: [router], stubs: { teleport: true } },
    attachTo: document.body,
  });
  return { wrapper, run, store, router };
}

/** 依按鈕文字找出某張卡片裡的按鈕。 */
export function buttonIn(card: ReturnType<ReturnType<typeof mount>["get"]>, label: string) {
  const btn = card.findAll("button").find((b) => b.text().trim() === label);
  if (!btn) throw new Error(`找不到按鈕：${label}`);
  return btn;
}

export function card(wrapper: ReturnType<typeof mount>, id: string) {
  return wrapper.get(`[data-record-id="${id}"]`);
}

/** 對話框內依欄位標籤（部分比對）找輸入元素。 */
export function fieldByLabel(wrapper: ReturnType<typeof mount>, label: string) {
  const dialog = wrapper.get("[role=dialog]");
  const field = dialog.findAll("label.field").find((l) => l.get(".field__label").text().includes(label));
  if (!field) throw new Error(`找不到欄位：${label}`);
  return field.get("input, select, textarea");
}

export function dialogLabels(wrapper: ReturnType<typeof mount>): string[] {
  return wrapper
    .get("[role=dialog]")
    .findAll(".field__label")
    .map((l) => l.text());
}

export async function submitDialog(wrapper: ReturnType<typeof mount>): Promise<void> {
  await wrapper.get("[role=dialog] form").trigger("submit");
  await flush();
}

export async function flush(): Promise<void> {
  for (let i = 0; i < 4; i += 1) await Promise.resolve();
  await new Promise((r) => setTimeout(r, 0));
}
