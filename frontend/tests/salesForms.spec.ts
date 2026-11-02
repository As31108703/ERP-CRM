import { afterEach, describe, expect, it } from "vitest";
import { lineChoices, linePayload, orderActions } from "../src/modules/sales/orderForms";
import SalesPage from "../src/modules/sales/SalesPage.vue";
import {
  BASE_WALLETS,
  buttonIn,
  card,
  dialogLabels,
  fieldByLabel,
  flush,
  mountPage,
  submitDialog,
  workspace,
} from "./pageHarness";

const PRODUCTS = [
  { id: "p1", sku: "DEMO-001", name: "星砂杯", price_minor: 1000, cost_minor: 400, active: true, on_hand: 10, reserved: 6, stock_value_minor: 4000, lots: [{ quantity: 10, cost_minor: 400 }] },
  { id: "p2", sku: "DEMO-002", name: "軌道燈", price_minor: 2500, cost_minor: 900, active: true, on_hand: 5, reserved: 0, stock_value_minor: 4500, lots: [{ quantity: 5, cost_minor: 900 }] },
];

function line(id: string, name: string, quantity: number, shipped: number, returned = 0) {
  return {
    id,
    product_id: "p1",
    name,
    price_minor: 1000,
    cost_minor: 400,
    quantity,
    shipped_quantity: shipped,
    returned_quantity: returned,
    shipped_cost_lots: shipped ? [{ quantity: shipped, cost_minor: 400, returned }] : [],
  };
}

const PAID_PARTLY_SHIPPED = {
  id: "o-paid",
  buyer_wallet_id: "w-buy",
  status: "partially_shipped",
  total_minor: 6000,
  paid_minor: 6000,
  refunded_minor: 0,
  lines: [line("l-done", "已出完品項", 2, 2), line("l-half", "出一半品項", 3, 1), line("l-none", "未出貨品項", 1, 0)],
};

const PENDING = {
  id: "o-pend",
  buyer_wallet_id: "w-buy",
  status: "pending",
  total_minor: 3000,
  paid_minor: 0,
  refunded_minor: 0,
  lines: [line("l-p", "待付款品項", 3, 0)],
};

/** 已出貨但仍有尾款的單據（用來單獨驗證「出貨後不得付款」這條規則）。 */
const SHIPPED_WITH_BALANCE = {
  ...PENDING,
  id: "o-ship-bal",
  status: "partially_shipped",
  paid_minor: 1000,
  lines: [line("l-s", "先出一件", 3, 1)],
};

const WS = workspace({ products: PRODUCTS, wallets: BASE_WALLETS, orders: [PAID_PARTLY_SHIPPED, PENDING, SHIPPED_WITH_BALANCE] });

afterEach(() => {
  document.body.innerHTML = "";
});

describe("order line forms", () => {
  it("ship form only lists lines with remaining and drops zero quantities", async () => {
    // 純函式：剩餘量計算與零數量剔除
    expect(lineChoices(PAID_PARTLY_SHIPPED, "ship").map((c) => [c.line.id, c.max])).toEqual([
      ["l-half", 2],
      ["l-none", 1],
    ]);
    expect(linePayload(lineChoices(PAID_PARTLY_SHIPPED, "ship"), { "line:l-half": 0, "line:l-none": 1 })).toEqual({
      lines: [{ line_id: "l-none", quantity: 1 }],
    });

    // 頁面：對話框只列出尚可出貨的品項，送出時只帶數量大於 0 的品項
    const { wrapper, run } = await mountPage(SalesPage, WS);
    await buttonIn(card(wrapper, "o-paid"), "分批出貨").trigger("click");
    const labels = dialogLabels(wrapper).join("|");
    expect(labels).toContain("出一半品項");
    expect(labels).toContain("未出貨品項");
    expect(labels).not.toContain("已出完品項");

    await fieldByLabel(wrapper, "出一半品項").setValue("0");
    await fieldByLabel(wrapper, "未出貨品項").setValue("1");
    await submitDialog(wrapper);
    expect(run).toHaveBeenCalledWith("POST", "/api/v1/sales/orders/o-paid/ship", {
      lines: [{ line_id: "l-none", quantity: 1 }],
    });
  });

  it("all-zero line form shows the validation message and sends nothing", async () => {
    const { wrapper, run } = await mountPage(SalesPage, WS);
    await buttonIn(card(wrapper, "o-paid"), "分批出貨").trigger("click");
    await submitDialog(wrapper);
    expect(run).not.toHaveBeenCalled();
    expect(wrapper.get("[role=dialog]").text()).toContain("請至少選擇一個品項與數量。");
  });

  it("quantities above the remaining amount are rejected locally", () => {
    const choices = lineChoices(PAID_PARTLY_SHIPPED, "ship");
    expect(linePayload(choices, { "line:l-half": 3 })).toBe("「出一半品項」最多可操作 2 件。");
  });

  it("return form lists shipped minus returned", () => {
    const order = { ...PAID_PARTLY_SHIPPED, lines: [line("a", "甲", 3, 3, 1), line("b", "乙", 2, 0)] };
    expect(lineChoices(order, "return").map((c) => [c.line.id, c.max])).toEqual([["a", 2]]);
  });
});

describe("order action rules", () => {
  it("pay disabled after any shipment", async () => {
    expect(orderActions(SHIPPED_WITH_BALANCE).pay).toBe(false);
    expect(orderActions(PENDING).pay).toBe(true);

    const { wrapper } = await mountPage(SalesPage, WS);
    expect(buttonIn(card(wrapper, "o-ship-bal"), "模擬付款").attributes("disabled")).toBeDefined();
    expect(buttonIn(card(wrapper, "o-pend"), "模擬付款").attributes("disabled")).toBeUndefined();
    // 出貨後也不能取消
    expect(buttonIn(card(wrapper, "o-ship-bal"), "取消訂單").attributes("disabled")).toBeDefined();
  });

  it("ship needs full payment; return needs something shipped; cancelled blocks all", () => {
    expect(orderActions(PENDING)).toEqual({ pay: true, ship: false, return: false, cancel: true });
    expect(orderActions(PAID_PARTLY_SHIPPED)).toEqual({ pay: false, ship: true, return: true, cancel: false });
    expect(orderActions({ ...PENDING, status: "cancelled" })).toEqual({
      pay: false,
      ship: false,
      return: false,
      cancel: false,
    });
    const allShipped = { ...PAID_PARTLY_SHIPPED, lines: [line("x", "甲", 2, 2)] };
    expect(orderActions(allShipped).ship).toBe(false);
  });

  it("pay form defaults to the remaining balance in SIM and sends minor units", async () => {
    const { wrapper, run } = await mountPage(SalesPage, WS);
    await buttonIn(card(wrapper, "o-pend"), "模擬付款").trigger("click");
    const amount = fieldByLabel(wrapper, "金額");
    expect((amount.element as HTMLInputElement).value).toBe("30");
    await amount.setValue("12.345");
    await submitDialog(wrapper);
    expect(run).not.toHaveBeenCalled();
    expect(wrapper.get("[role=dialog]").text()).toContain("最多兩位小數");

    await amount.setValue("12.34");
    await submitDialog(wrapper);
    expect(run).toHaveBeenCalledWith("POST", "/api/v1/sales/orders/o-pend/pay", { amount_minor: 1234 });
    await flush();
    expect(wrapper.find("[role=dialog]").exists()).toBe(false);
  });

  it("cancel asks for confirmation then posts an empty body", async () => {
    const { wrapper, run } = await mountPage(SalesPage, WS);
    await buttonIn(card(wrapper, "o-pend"), "取消訂單").trigger("click");
    expect(wrapper.get("[role=dialog]").text()).toContain("確認執行此模擬操作？");
    await submitDialog(wrapper);
    expect(run).toHaveBeenCalledWith("POST", "/api/v1/sales/orders/o-pend/cancel", {});
  });

  it("order cards keep their original number and show buyer and totals", async () => {
    const { wrapper } = await mountPage(SalesPage, WS);
    const c = card(wrapper, "o-pend");
    expect(c.text()).toContain("訂單 2");
    expect(c.text()).toContain("測試買家甲");
    expect(c.text()).toContain("30.00 SIM");
    expect(c.text()).toContain("待付款");
  });

  it("create order is blocked without a buyer wallet and explains why", async () => {
    const { wrapper } = await mountPage(SalesPage, workspace({ products: PRODUCTS, wallets: BASE_WALLETS.slice(0, 3) }));
    const create = wrapper.get("[data-testid=create-order]");
    expect(create.attributes("disabled")).toBeDefined();
    expect(wrapper.text()).toContain("先建立買家錢包");
  });

  it("create order sends only products with a quantity", async () => {
    const { wrapper, run } = await mountPage(SalesPage, WS);
    await wrapper.get("[data-testid=create-order]").trigger("click");
    await fieldByLabel(wrapper, "買家").setValue("w-buy");
    await fieldByLabel(wrapper, "軌道燈").setValue("2");
    await submitDialog(wrapper);
    expect(run).toHaveBeenCalledWith("POST", "/api/v1/sales/orders", {
      buyer_wallet_id: "w-buy",
      lines: [{ product_id: "p2", quantity: 2 }],
    });
  });
});
