import { afterEach, describe, expect, it } from "vitest";
import CrmPage from "../src/modules/crm/CrmPage.vue";
import InventoryPage from "../src/modules/inventory/InventoryPage.vue";
import ServicesPage from "../src/modules/services/ServicesPage.vue";
import WalletsPage from "../src/modules/wallets/WalletsPage.vue";
import { BASE_WALLETS, buttonIn, card, fieldByLabel, mountPage, submitDialog, workspace } from "./pageHarness";

afterEach(() => {
  document.body.innerHTML = "";
});

const PRODUCT = {
  id: "p1",
  sku: "DEMO-001",
  name: "星砂杯",
  price_minor: 1000,
  cost_minor: 400,
  active: true,
  on_hand: 10,
  reserved: 3,
  stock_value_minor: 4000,
  lots: [
    { quantity: 6, cost_minor: 400 },
    { quantity: 4, cost_minor: 400 },
  ],
};

describe("inventory page", () => {
  it("shows stock tiles, lots and SKU", async () => {
    const { wrapper } = await mountPage(InventoryPage, workspace({ products: [PRODUCT] }), { module: "inventory" });
    const c = card(wrapper, "p1");
    expect(c.get("[data-stock=available]").text()).toContain("7");
    expect(c.get("[data-stock=reserved]").text()).toContain("3");
    expect(c.get("[data-stock=on_hand]").text()).toContain("10");
    expect(c.text()).toContain("DEMO-001");
    expect(c.text()).toContain("10.00 SIM");
    expect(c.text()).toContain("6 × 4.00 SIM");
  });

  it("receive posts the quantity; edit sends minor prices", async () => {
    const { wrapper, run } = await mountPage(InventoryPage, workspace({ products: [PRODUCT] }), { module: "inventory" });
    await buttonIn(card(wrapper, "p1"), "採購入庫").trigger("click");
    await fieldByLabel(wrapper, "數量").setValue("5");
    await submitDialog(wrapper);
    expect(run).toHaveBeenCalledWith("POST", "/api/v1/inventory/products/p1/receive", { quantity: 5 });

    await buttonIn(card(wrapper, "p1"), "編輯商品").trigger("click");
    expect((fieldByLabel(wrapper, "售價").element as HTMLInputElement).value).toBe("10");
    await fieldByLabel(wrapper, "售價").setValue("12.5");
    await fieldByLabel(wrapper, "成本").setValue("0");
    await submitDialog(wrapper);
    expect(run).toHaveBeenLastCalledWith("PATCH", "/api/v1/inventory/products/p1", {
      name: "星砂杯",
      sku: "DEMO-001",
      price_minor: 1250,
      cost_minor: 0,
    });
  });

  it("price must be at least 0.01 SIM", async () => {
    const { wrapper, run } = await mountPage(InventoryPage, workspace({ products: [PRODUCT] }), { module: "inventory" });
    await buttonIn(card(wrapper, "p1"), "編輯商品").trigger("click");
    await fieldByLabel(wrapper, "售價").setValue("0");
    await submitDialog(wrapper);
    expect(run).not.toHaveBeenCalled();
    expect(wrapper.get("[role=dialog]").text()).toContain("售價");
  });

  it("new product defaults to 100 / 50 SIM", async () => {
    const { wrapper, run } = await mountPage(InventoryPage, workspace(), { module: "inventory" });
    await wrapper.get("[data-testid=create-product]").trigger("click");
    await fieldByLabel(wrapper, "商品名稱").setValue("新品");
    await fieldByLabel(wrapper, "SKU").setValue("NEW-1");
    await submitDialog(wrapper);
    expect(run).toHaveBeenCalledWith("POST", "/api/v1/inventory/products", {
      name: "新品",
      sku: "NEW-1",
      price_minor: 10000,
      cost_minor: 5000,
    });
  });
});

describe("wallets page", () => {
  const LEDGER = [
    { id: "lg1", kind: "wallet.fund", reference_id: "lg1", created_at: "2026-11-01T01:00:00Z", entries: [{ wallet_id: "w-fau", amount_minor: -10000 }, { wallet_id: "w-buy", amount_minor: 10000 }] },
    { id: "lg2", kind: "order.pay", reference_id: "o1", created_at: "2026-11-01T02:00:00Z", entries: [{ wallet_id: "w-buy", amount_minor: -3000 }, { wallet_id: "w-biz", amount_minor: 3000 }] },
  ];

  it("fund is offered only for business and buyer wallets", async () => {
    const { wrapper, run } = await mountPage(WalletsPage, workspace({ wallets: BASE_WALLETS, ledger: LEDGER }), { module: "wallets" });
    expect(card(wrapper, "w-biz").text()).toContain("補充測試幣");
    expect(card(wrapper, "w-buy").text()).toContain("補充測試幣");
    expect(card(wrapper, "w-sup").text()).not.toContain("補充測試幣");
    expect(card(wrapper, "w-fau").text()).not.toContain("補充測試幣");
    expect(card(wrapper, "w-fau").text()).toContain("測試幣來源");
    expect(card(wrapper, "w-buy").text()).toContain("測試買家甲");

    await buttonIn(card(wrapper, "w-buy"), "補充測試幣").trigger("click");
    expect((fieldByLabel(wrapper, "金額").element as HTMLInputElement).value).toBe("1000");
    await submitDialog(wrapper);
    expect(run).toHaveBeenCalledWith("POST", "/api/v1/wallets/w-buy/fund", { amount_minor: 100000 });
  });

  it("ledger is newest first with kind labels and wallet names", async () => {
    const { wrapper } = await mountPage(WalletsPage, workspace({ wallets: BASE_WALLETS, ledger: LEDGER }), { module: "wallets" });
    const items = wrapper.findAll("[data-testid=ledger-item]");
    expect(items).toHaveLength(2);
    expect(items[0].text()).toContain("移轉 2");
    expect(items[0].text()).toContain("訂單付款");
    expect(items[0].text()).toContain("測試買家甲");
    expect(items[0].text()).toContain("-30.00 SIM");
    expect(items[1].text()).toContain("補充測試幣");
  });

  it("new buyer wallet posts kind buyer", async () => {
    const { wrapper, run } = await mountPage(WalletsPage, workspace({ wallets: BASE_WALLETS }), { module: "wallets" });
    await wrapper.get("[data-testid=create-wallet]").trigger("click");
    await fieldByLabel(wrapper, "名稱").setValue("乙");
    await submitDialog(wrapper);
    expect(run).toHaveBeenCalledWith("POST", "/api/v1/wallets", { kind: "buyer", name: "乙" });
  });
});

describe("crm page", () => {
  const CUSTOMERS = [{ id: "c1", name: "銀河商行", notes: "老客戶" }];
  const CRM = workspace({
    customers: CUSTOMERS,
    contacts: [{ id: "k1", name: "林小姐", customer_id: "c1", email: "lin@example.test" }],
    deals: [{ id: "d1", title: "年度採購", customer_id: "c1", status: "new", notes: "" }],
    cases: [{ id: "cs1", title: "導入案", customer_id: "c1", status: "open", notes: "" }],
  });

  it("contact, deal and case buttons need a customer", async () => {
    const { wrapper } = await mountPage(CrmPage, workspace(), { module: "crm" });
    for (const id of ["create-contact", "create-deal", "create-case"]) {
      expect(wrapper.get(`[data-testid=${id}]`).attributes("disabled"), id).toBeDefined();
    }
    expect(wrapper.get("[data-testid=create-customer]").attributes("disabled")).toBeUndefined();
  });

  it("customer card lists its contacts", async () => {
    const { wrapper } = await mountPage(CrmPage, CRM, { module: "crm" });
    expect(card(wrapper, "c1").text()).toContain("林小姐 · lin@example.test");
  });

  it("losing a deal requires a reason", async () => {
    const { wrapper, run } = await mountPage(CrmPage, CRM, { module: "crm" });
    await buttonIn(card(wrapper, "d1"), "更新商機").trigger("click");
    await fieldByLabel(wrapper, "階段").setValue("lost");
    await submitDialog(wrapper);
    expect(run).not.toHaveBeenCalled();
    expect(wrapper.get("[role=dialog]").text()).toContain("未成交原因");
    await fieldByLabel(wrapper, "未成交原因").setValue("預算不足");
    await submitDialog(wrapper);
    expect(run).toHaveBeenCalledWith("PATCH", "/api/v1/crm/deals/d1", {
      title: "年度採購",
      status: "lost",
      lost_reason: "預算不足",
    });
  });

  it("followup posts the note", async () => {
    const { wrapper, run } = await mountPage(CrmPage, CRM, { module: "crm" });
    await buttonIn(card(wrapper, "d1"), "記錄跟進").trigger("click");
    await fieldByLabel(wrapper, "聯繫").setValue("已寄型錄");
    await submitDialog(wrapper);
    expect(run).toHaveBeenCalledWith("POST", "/api/v1/crm/deals/d1/followups", { note: "已寄型錄" });
  });

  it("case quote defaults to 100 SIM and a 7-day ISO expiry", async () => {
    const { wrapper, run } = await mountPage(CrmPage, CRM, { module: "crm" });
    await buttonIn(card(wrapper, "cs1"), "建立報價").trigger("click");
    const before = Date.now();
    await submitDialog(wrapper);
    const [method, path, body] = run.mock.calls[0] as unknown as [string, string, { case_id: string; amount_minor: number; expires_at: string }];
    expect([method, path]).toEqual(["POST", "/api/v1/crm/quotes"]);
    expect(body.case_id).toBe("cs1");
    expect(body.amount_minor).toBe(10000);
    const delta = Date.parse(body.expires_at) - before;
    expect(delta).toBeGreaterThan(7 * 86400000 - 120000);
    expect(delta).toBeLessThan(7 * 86400000 + 60000);
  });

  it("targets the record from the route query", async () => {
    const { wrapper } = await mountPage(CrmPage, CRM, { module: "crm", query: { target: "deal:d1" } });
    expect(card(wrapper, "d1").classes()).toContain("is-target");
    expect(card(wrapper, "c1").classes()).not.toContain("is-target");
  });
});

describe("services page", () => {
  const future = new Date(Date.now() + 86400000).toISOString();
  const past = new Date(Date.now() - 86400000).toISOString();
  const SVC = workspace({
    wallets: BASE_WALLETS,
    customers: [{ id: "c1", name: "銀河商行" }],
    cases: [{ id: "cs1", title: "導入案", customer_id: "c1", status: "open" }],
    quotes: [
      { id: "q-draft", case_id: "cs1", amount_minor: 10000, expires_at: future, status: "draft" },
      { id: "q-live", case_id: "cs1", amount_minor: 12000, expires_at: future, status: "issued", digest: "dg-live" },
      { id: "q-old", case_id: "cs1", amount_minor: 9000, expires_at: past, status: "issued", digest: "dg-old" },
    ],
    services: [
      { id: "s-draft", case_id: "cs1", title: "導入案", amount_minor: 20000, paid_minor: 0, status: "draft", deliveries: [], latest_delivery_id: null },
      {
        id: "s-sub",
        case_id: "cs1",
        title: "導入案",
        amount_minor: 20000,
        paid_minor: 0,
        status: "submitted",
        deliveries: [
          { id: "dv1", revision: 1, artifact_ref: "spec-v1.pdf", digest: "d1" },
          { id: "dv2", revision: 2, artifact_ref: "spec-v2.pdf", digest: "d2" },
        ],
        latest_delivery_id: "dv2",
      },
      { id: "s-acc", case_id: "cs1", title: "導入案", amount_minor: 20000, paid_minor: 5000, status: "accepted", deliveries: [{ id: "dv3", revision: 1, artifact_ref: "x", digest: "d3" }], latest_delivery_id: "dv3" },
    ],
  });

  it("quote buttons follow status and expiry", async () => {
    const { wrapper, run } = await mountPage(ServicesPage, SVC, { module: "services" });
    expect(buttonIn(card(wrapper, "q-draft"), "發出報價").attributes("disabled")).toBeUndefined();
    expect(buttonIn(card(wrapper, "q-live"), "發出報價").attributes("disabled")).toBeDefined();
    expect(buttonIn(card(wrapper, "q-live"), "模擬確認").attributes("disabled")).toBeUndefined();
    expect(buttonIn(card(wrapper, "q-old"), "模擬確認").attributes("disabled")).toBeDefined();
    expect(card(wrapper, "q-live").text()).toContain("導入案 · 報價 2");

    await buttonIn(card(wrapper, "q-live"), "模擬確認").trigger("click");
    expect(run).toHaveBeenCalledWith("POST", "/api/v1/crm/quotes/q-live/confirm", { digest: "dg-live" });
    await buttonIn(card(wrapper, "q-draft"), "發出報價").trigger("click");
    expect(run).toHaveBeenLastCalledWith("POST", "/api/v1/crm/quotes/q-draft/issue", {});
  });

  it("service actions follow status; accept uses the latest delivery", async () => {
    const { wrapper, run } = await mountPage(ServicesPage, SVC, { module: "services" });
    const draft = card(wrapper, "s-draft");
    expect(buttonIn(draft, "模擬確認服務").attributes("disabled")).toBeUndefined();
    expect(buttonIn(draft, "提交交付版本").attributes("disabled")).toBeDefined();
    expect(buttonIn(draft, "模擬驗收").attributes("disabled")).toBeDefined();

    const sub = card(wrapper, "s-sub");
    expect(sub.text()).toContain("交付 v2 · 最新");
    expect(buttonIn(sub, "提交交付版本").attributes("disabled")).toBeUndefined();
    await buttonIn(sub, "模擬驗收").trigger("click");
    expect(run).toHaveBeenCalledWith("POST", "/api/v1/services/s-sub/accept", { delivery_id: "dv2", digest: "d2" });
    await buttonIn(sub, "要求補件").trigger("click");
    expect(run).toHaveBeenLastCalledWith("POST", "/api/v1/services/s-sub/request-changes", { delivery_id: "dv2", digest: "d2" });

    const acc = card(wrapper, "s-acc");
    // 已收部分款項：不可再提交交付
    expect(buttonIn(acc, "提交交付版本").attributes("disabled")).toBeDefined();
    await buttonIn(acc, "模擬服務付款").trigger("click");
    expect((fieldByLabel(wrapper, "金額").element as HTMLInputElement).value).toBe("150");
    await submitDialog(wrapper);
    expect(run).toHaveBeenCalledTimes(2);
    expect(wrapper.get("[role=dialog]").text()).toContain("買家");
    await fieldByLabel(wrapper, "買家").setValue("w-buy");
    await submitDialog(wrapper);
    expect(run).toHaveBeenLastCalledWith("POST", "/api/v1/services/s-acc/pay", { buyer_wallet_id: "w-buy", amount_minor: 15000 });
  });

  it("quote and service creation need cases", async () => {
    const { wrapper } = await mountPage(ServicesPage, workspace(), { module: "services" });
    expect(wrapper.get("[data-testid=create-quote]").attributes("disabled")).toBeDefined();
    expect(wrapper.get("[data-testid=create-service]").attributes("disabled")).toBeDefined();
    expect(wrapper.text()).toContain("先建立客戶案件");
  });
});
