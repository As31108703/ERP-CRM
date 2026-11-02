<script setup lang="ts">
import { computed } from "vue";
import { simInput, formatSim } from "../../lib/format";
import { findRow, list, num, recordName, statusKey, statusLabel, type Row } from "../../lib/records";
import DataSection from "../../ui/DataSection.vue";
import EmptyState from "../../ui/EmptyState.vue";
import RecordCard from "../../ui/RecordCard.vue";
import { API_V1, isError, readMoney, useCommandForm } from "../shared/commandForm";
import { createBlocker, createSpec, moneyField } from "../shared/createForms";
import CommandDialog from "../shared/CommandDialog.vue";
import PageHead from "../shared/PageHead.vue";
import { usePage } from "../shared/usePage";
import { lineChoices, lineFields, linePayload, orderActions, type LineMode } from "./orderForms";

const { store, ws, resetKey, rows, enabled, readiness, targetId, clearTarget, searchText } = usePage();
const form = useCommandForm();

const orders = computed(() => rows("orders"));
/** 訂單編號依原始順序，篩選後仍保留。 */
const orderNo = computed(() => new Map(orders.value.map((o, i) => [o.id, i + 1])));
const createReason = computed(() => createBlocker("order", ws.value));

function buyerName(order: Row): string {
  return recordName(findRow(ws.value, "wallets", order.buyer_wallet_id), "錢包");
}

function orderSearch(order: Row): string {
  const lines = list(order, "lines").map((l) => recordName(l, "品項"));
  return searchText("order", order, [`訂單 ${orderNo.value.get(order.id)}`, buyerName(order), ...lines]);
}

const path = (order: Row, action = "") => `${API_V1}/sales/orders/${encodeURIComponent(order.id)}${action ? `/${action}` : ""}`;

function openPay(order: Row): void {
  form.open({
    title: "模擬訂單付款",
    fields: [moneyField("amount_minor", "付款金額（SIM）", "可部分付款；全額付清後才能出貨")],
    initial: { amount_minor: simInput(num(order, "total_minor") - num(order, "paid_minor")) },
    submitLabel: "確認付款",
    build: (v) => {
      const amount = readMoney(v, "amount_minor", "付款金額");
      return isError(amount) ? amount.error : { method: "POST", path: path(order, "pay"), body: { amount_minor: amount } };
    },
  });
}

function openLines(order: Row, mode: LineMode): void {
  const choices = lineChoices(order, mode);
  form.open({
    title: mode === "ship" ? "分批出貨" : "部分退貨",
    fields: lineFields(choices, mode),
    initial: Object.fromEntries(choices.map((c) => [`line:${c.line.id}`, 0])),
    submitLabel: mode === "ship" ? "確認出貨" : "確認退貨",
    build: (v) => {
      const body = linePayload(choices, v);
      return typeof body === "string" ? body : { method: "POST", path: path(order, mode), body };
    },
  });
}

function openCancel(order: Row): void {
  form.open({
    title: "取消訂單並退回已付測試幣",
    fields: [],
    submitLabel: "確認取消",
    build: () => ({ method: "POST", path: path(order, "cancel"), body: {} }),
  });
}

function openCreate(): void {
  form.open(createSpec("order", ws.value));
}
</script>

<template>
  <div class="mpage" data-testid="page-sales">
    <PageHead code="MODULE · SALES · ORD" title="模擬訂單" lead="多品項接單、部分付款、分批出貨與部分退貨；全額付清後才能出貨，所有金額都是 SIM 測試幣。">
      <button type="button" class="btn btn--primary" data-testid="create-order" :disabled="Boolean(createReason) || store.busy" @click="openCreate">
        建立訂單
      </button>
      <span v-if="createReason" class="phead__reason">{{ createReason }}</span>
    </PageHead>

    <EmptyState v-if="!enabled('sales')" title="尚未啟用此模組" text="請到設定頁切換產業範本或調整模組。" />
    <DataSection
      v-else
      title="訂單"
      code="ORD-LOG"
      :items="orders"
      :search-text="orderSearch"
      :status-of="(o: Row) => statusKey('order', o)"
      :status-label="statusLabel"
      :target-id="targetId('order')"
      :reset-key="resetKey"
      empty-text="還沒有訂單。先準備商品庫存與買家錢包，再建立第一張模擬訂單。"
      @clear-target="clearTarget"
    >
      <template #item="{ item }">
        <RecordCard kind="order" :row="item" :readiness="readiness('order', item.id)">
          <template #title>訂單 <span class="num">{{ orderNo.get(item.id) }}</span></template>
          <template #meta>{{ buyerName(item) }}</template>
          <ul class="mpage__lines">
            <li v-for="l in list(item, 'lines')" :key="String(l.id)">
              <strong>{{ recordName(l, "品項") }} × <span class="num">{{ num(l, "quantity") }}</span></strong>
              <span class="mpage__dim">已出 <span class="num">{{ num(l, "shipped_quantity") }}</span>／已退 <span class="num">{{ num(l, "returned_quantity") }}</span></span>
            </li>
          </ul>
          <p class="mpage__money">
            總額 <span class="num">{{ formatSim(num(item, "total_minor")) }}</span> · 已付
            <span class="num">{{ formatSim(num(item, "paid_minor")) }}</span> · 已退款
            <span class="num">{{ formatSim(num(item, "refunded_minor")) }}</span>
          </p>
          <template #actions>
            <button type="button" class="btn btn--sm" :disabled="!orderActions(item).pay || store.busy" @click="openPay(item)">模擬付款</button>
            <button type="button" class="btn btn--sm" :disabled="!orderActions(item).ship || store.busy" @click="openLines(item, 'ship')">分批出貨</button>
            <button type="button" class="btn btn--sm" :disabled="!orderActions(item).return || store.busy" @click="openLines(item, 'return')">部分退貨</button>
            <button type="button" class="btn btn--sm btn--danger" :disabled="!orderActions(item).cancel || store.busy" @click="openCancel(item)">取消訂單</button>
          </template>
        </RecordCard>
      </template>
    </DataSection>

    <CommandDialog :form="form" />
  </div>
</template>

<style scoped src="../shared/page.css"></style>
