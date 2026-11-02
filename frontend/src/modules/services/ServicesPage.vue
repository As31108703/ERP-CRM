<script setup lang="ts">
import { computed } from "vue";
import { formatSim, simInput } from "../../lib/format";
import { findRow, list, num, recordName, statusKey, statusLabel, str, type Row } from "../../lib/records";
import DataSection from "../../ui/DataSection.vue";
import EmptyState from "../../ui/EmptyState.vue";
import RecordCard from "../../ui/RecordCard.vue";
import QuoteList from "../crm/QuoteList.vue";
import { latestDelivery, quoteSpec, serviceTitle } from "../crm/quoteForms";
import { API_V1, isError, readMoney, useCommandForm } from "../shared/commandForm";
import CommandDialog from "../shared/CommandDialog.vue";
import { buyerField, createBlocker, createSpec, moneyField } from "../shared/createForms";
import PageHead from "../shared/PageHead.vue";
import { usePage } from "../shared/usePage";

const { store, ws, resetKey, rows, enabled, readiness, targetId, clearTarget, searchText } = usePage();
const form = useCommandForm();

const services = computed(() => rows("services"));
const quoteReason = computed(() =>
  !enabled("crm") ? "尚未啟用客戶與商機模組" : rows("cases").length === 0 ? "先建立客戶案件" : null,
);
const serviceReason = computed(() => createBlocker("service", ws.value));

const DELIVERABLE = ["confirmed", "submitted", "changes_requested", "accepted"];

const path = (s: Row, action: string) => `${API_V1}/services/${encodeURIComponent(s.id)}/${action}`;

function rules(s: Row) {
  const status = str(s, "status");
  const amount = num(s, "amount_minor");
  const paid = num(s, "paid_minor");
  const latest = latestDelivery(s);
  return {
    confirm: status === "draft",
    deliver: DELIVERABLE.includes(status) && paid === 0,
    review: status === "submitted" && latest !== undefined,
    pay: status === "accepted" && paid < amount,
  };
}

function review(s: Row, action: "accept" | "request-changes"): void {
  const latest = latestDelivery(s);
  if (!latest) return;
  void form.direct("POST", path(s, action), { delivery_id: latest.id, digest: latest.digest });
}

function openDeliver(s: Row): void {
  form.open({
    title: "提交交付版本",
    fields: [{ name: "artifact_ref", label: "交付內容／檔案參照（模擬）", required: true, hint: "例如文件名稱或版本代號，不會上傳實體檔案" }],
    submitLabel: "提交交付",
    build: (v) => ({ method: "POST", path: path(s, "deliver"), body: { artifact_ref: v.artifact_ref } }),
  });
}

function openPay(s: Row): void {
  form.open({
    title: "模擬服務付款",
    fields: [buyerField(ws.value), moneyField("amount_minor", "付款金額（SIM）", "可部分付款")],
    initial: { amount_minor: simInput(num(s, "amount_minor") - num(s, "paid_minor")) },
    submitLabel: "確認付款",
    build: (v) => {
      const amount = readMoney(v, "amount_minor", "付款金額");
      return isError(amount)
        ? amount.error
        : { method: "POST", path: path(s, "pay"), body: { buyer_wallet_id: v.buyer_wallet_id, amount_minor: amount } };
    },
  });
}

function search(s: Row): string {
  const c = findRow(ws.value, "cases", s.case_id);
  const customer = findRow(ws.value, "customers", c?.customer_id);
  return searchText("service", s, [serviceTitle(ws.value, s), c ? recordName(c) : undefined, customer ? recordName(customer) : undefined]);
}
</script>

<template>
  <div class="mpage" data-testid="page-services">
    <PageHead code="MODULE · SERVICES · DLV" title="報價與服務" lead="報價版本保留快照；交付與驗收只處理最新版本，驗收後才能收取測試幣。所有確認僅供模擬。">
      <button
        type="button"
        class="btn"
        data-testid="create-quote"
        :disabled="Boolean(quoteReason) || store.busy"
        @click="form.open(quoteSpec(ws))"
      >
        建立報價
      </button>
      <button
        type="button"
        class="btn btn--primary"
        data-testid="create-service"
        :disabled="Boolean(serviceReason) || store.busy"
        @click="form.open(createSpec('service', ws))"
      >
        建立服務
      </button>
      <span v-if="serviceReason || quoteReason" class="phead__reason">{{ serviceReason || quoteReason }}</span>
    </PageHead>

    <EmptyState v-if="!enabled('services')" title="尚未啟用此模組" text="請到設定頁切換產業範本或調整模組。" />
    <div v-else class="mpage__grid">
      <QuoteList />
      <DataSection
        title="服務交付"
        code="SVC-DOCK"
        :items="services"
        :search-text="search"
        :status-of="(s: Row) => statusKey('service', s)"
        :status-label="statusLabel"
        :target-id="targetId('service')"
        :reset-key="resetKey"
        empty-text="還沒有服務。從客戶案件建立第一筆服務。"
        @clear-target="clearTarget"
      >
        <template #item="{ item }">
          <RecordCard kind="service" :row="item" :readiness="readiness('service', item.id)">
            <template #title>{{ serviceTitle(ws, item) }}</template>
            <p class="mpage__money">
              <span class="num">{{ formatSim(num(item, "amount_minor")) }}</span> · 已收
              <span class="num">{{ formatSim(num(item, "paid_minor")) }}</span>
            </p>
            <ul v-if="list(item, 'deliveries').length" class="mpage__lines">
              <li v-for="d in list(item, 'deliveries')" :key="d.id">
                <strong>交付 v{{ num(d, "revision") }}{{ d.id === item.latest_delivery_id ? " · 最新" : "" }}</strong>
                <span class="mpage__dim">{{ str(d, "artifact_ref") }}</span>
              </li>
            </ul>
            <template #actions>
              <button
                type="button"
                class="btn btn--sm"
                :disabled="!rules(item).confirm || store.busy"
                @click="form.direct('POST', path(item, 'confirm'))"
              >
                模擬確認服務
              </button>
              <button type="button" class="btn btn--sm" :disabled="!rules(item).deliver || store.busy" @click="openDeliver(item)">
                提交交付版本
              </button>
              <button type="button" class="btn btn--sm" :disabled="!rules(item).review || store.busy" @click="review(item, 'accept')">
                模擬驗收
              </button>
              <button
                type="button"
                class="btn btn--sm"
                :disabled="!rules(item).review || store.busy"
                @click="review(item, 'request-changes')"
              >
                要求補件
              </button>
              <button type="button" class="btn btn--sm" :disabled="!rules(item).pay || store.busy" @click="openPay(item)">
                模擬服務付款
              </button>
            </template>
          </RecordCard>
        </template>
      </DataSection>
    </div>

    <CommandDialog :form="form" />
  </div>
</template>

<style scoped src="../shared/page.css"></style>
