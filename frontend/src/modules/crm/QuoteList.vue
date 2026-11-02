<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from "vue";
import { formatDateTime, formatSim } from "../../lib/format";
import { findRow, num, recordName, statusKey, statusLabel, str, type Row } from "../../lib/records";
import DataSection from "../../ui/DataSection.vue";
import RecordCard from "../../ui/RecordCard.vue";
import { API_V1, useCommandForm } from "../shared/commandForm";
import { usePage } from "../shared/usePage";
import { quoteExpired, quoteTitle } from "./quoteForms";

/** 報價版本清單（CRM 與服務頁共用）。發出與確認不需表單，直接送出命令。 */
const { store, ws, resetKey, rows, enabled, readiness, targetId, clearTarget, searchText } = usePage();
const { direct } = useCommandForm();

const quotes = computed(() => rows("quotes"));

// 到期判斷需要隨時間更新，每 30 秒重算一次。
const now = ref(Date.now());
const timer = setInterval(() => (now.value = Date.now()), 30_000);
onBeforeUnmount(() => clearInterval(timer));

const path = (q: Row, action: string) => `${API_V1}/crm/quotes/${encodeURIComponent(q.id)}/${action}`;

function canIssue(q: Row): boolean {
  return str(q, "status") === "draft" && enabled("crm");
}

function canConfirm(q: Row): boolean {
  return str(q, "status") === "issued" && !quoteExpired(q, now.value) && enabled("crm");
}

function search(q: Row): string {
  const c = findRow(ws.value, "cases", q.case_id);
  const customer = findRow(ws.value, "customers", c?.customer_id);
  return searchText("quote", q, [quoteTitle(ws.value, q), customer ? recordName(customer) : undefined]);
}
</script>

<template>
  <DataSection
    title="報價版本"
    code="QTE-VAULT"
    :items="quotes"
    :search-text="search"
    :status-of="(q: Row) => statusKey('quote', q)"
    :status-label="statusLabel"
    :target-id="targetId('quote')"
    :reset-key="resetKey"
    empty-text="還沒有報價。從案件建立報價版本，發出後內容即凍結。"
    @clear-target="clearTarget"
  >
    <template #item="{ item }">
      <RecordCard kind="quote" :row="item" :readiness="readiness('quote', item.id)">
        <template #title>{{ quoteTitle(ws, item) }}</template>
        <p class="mpage__money">
          <span class="num">{{ formatSim(num(item, "amount_minor")) }}</span> · 到期
          <span class="num">{{ formatDateTime(item.expires_at) }}</span>
          <span v-if="quoteExpired(item, now) && str(item, 'status') === 'issued'" class="badge badge--warn">已過期</span>
        </p>
        <template #actions>
          <button type="button" class="btn btn--sm" :disabled="!canIssue(item) || store.busy" @click="direct('POST', path(item, 'issue'))">
            發出報價
          </button>
          <button
            type="button"
            class="btn btn--sm"
            :disabled="!canConfirm(item) || store.busy"
            @click="direct('POST', path(item, 'confirm'), { digest: item.digest })"
          >
            模擬確認
          </button>
        </template>
      </RecordCard>
    </template>
  </DataSection>
</template>

<style scoped src="../shared/page.css"></style>
