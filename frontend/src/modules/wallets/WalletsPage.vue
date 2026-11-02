<script setup lang="ts">
import { computed } from "vue";
import { formatDateTime, formatSim, simInput } from "../../lib/format";
import { findRow, list, num, recordName, statusKey, statusLabel, str, type Rec, type Row } from "../../lib/records";
import DataSection from "../../ui/DataSection.vue";
import EmptyState from "../../ui/EmptyState.vue";
import HudPanel from "../../ui/HudPanel.vue";
import RecordCard from "../../ui/RecordCard.vue";
import { API_V1, isError, readMoney, useCommandForm } from "../shared/commandForm";
import { createBlocker, createSpec, moneyField } from "../shared/createForms";
import CommandDialog from "../shared/CommandDialog.vue";
import PageHead from "../shared/PageHead.vue";
import { usePage } from "../shared/usePage";

const { store, ws, resetKey, rows, enabled, readiness, targetId, clearTarget, searchText } = usePage();
const form = useCommandForm();

const wallets = computed(() => rows("wallets"));
const createReason = computed(() => createBlocker("wallet", ws.value));

/** 系統錢包（商家、供應商、測試幣來源）以種類為標題，買家錢包用名稱。 */
const SYSTEM_KINDS = ["business", "supplier", "faucet"];
const FUNDABLE = ["business", "buyer"];

function walletTitle(w: Row | undefined): string {
  if (!w) return "（已刪除）";
  const kind = str(w, "kind");
  return SYSTEM_KINDS.includes(kind) ? statusLabel(kind) : recordName(w, "錢包");
}

const LEDGER_LABELS: Record<string, string> = {
  "wallet.fund": "補充測試幣",
  "inventory.receive": "採購入庫",
  "order.pay": "訂單付款",
  "order.return": "訂單退款",
  "order.cancel": "取消退款",
  "service.pay": "服務付款",
};

/** 移轉紀錄：新到舊，編號保留原始順序。 */
const ledger = computed(() =>
  rows("ledger")
    .map((row, i) => ({ row, no: i + 1 }))
    .reverse(),
);

function openFund(w: Row): void {
  form.open({
    title: `補充測試幣：${walletTitle(w)}`,
    fields: [moneyField("amount_minor", "金額（SIM）", "由測試幣來源撥入，僅供模擬")],
    initial: { amount_minor: simInput(100000) },
    submitLabel: "確認補充",
    build: (v) => {
      const amount = readMoney(v, "amount_minor", "金額");
      return isError(amount)
        ? amount.error
        : { method: "POST", path: `${API_V1}/wallets/${encodeURIComponent(w.id)}/fund`, body: { amount_minor: amount } };
    },
  });
}
</script>

<template>
  <div class="mpage" data-testid="page-wallets">
    <PageHead code="MODULE · WALLETS · LEDGER" title="測試幣流水" lead="商家、供應商與買家的 SIM 錢包；每筆移轉都留下兩筆分錄，總額永遠為零。">
      <button
        type="button"
        class="btn btn--primary"
        data-testid="create-wallet"
        :disabled="Boolean(createReason) || store.busy"
        @click="form.open(createSpec('wallet', ws))"
      >
        新增買家錢包
      </button>
      <span v-if="createReason" class="phead__reason">{{ createReason }}</span>
    </PageHead>

    <EmptyState v-if="!enabled('wallets')" title="尚未啟用此模組" text="請到設定頁切換產業範本或調整模組。" />
    <div v-else class="mpage__grid">
      <DataSection
        title="錢包"
        code="WAL-ARRAY"
        :items="wallets"
        :search-text="(w: Row) => searchText('wallet', w, [walletTitle(w)])"
        :status-of="(w: Row) => statusKey('wallet', w)"
        :status-label="statusLabel"
        :target-id="targetId('wallet')"
        :reset-key="resetKey"
        empty-text="還沒有錢包。"
        @clear-target="clearTarget"
      >
        <template #item="{ item }">
          <RecordCard kind="wallet" :row="item" :readiness="readiness('wallet', item.id)">
            <template #title>{{ walletTitle(item) }}</template>
            <template #meta>{{ statusLabel(str(item, "kind")) }}</template>
            <p class="mpage__balance num">{{ formatSim(num(item, "balance_minor")) }}</p>
            <template v-if="FUNDABLE.includes(str(item, 'kind'))" #actions>
              <button type="button" class="btn btn--sm" :disabled="store.busy" @click="openFund(item)">補充測試幣</button>
            </template>
          </RecordCard>
        </template>
      </DataSection>

      <HudPanel title="移轉紀錄" code="TX-STREAM">
        <EmptyState v-if="ledger.length === 0" title="尚無移轉" text="補充測試幣、採購入庫或付款後會出現在這裡。" />
        <ol v-else class="mpage__ledger">
          <li v-for="{ row, no } in ledger" :key="row.id" data-testid="ledger-item">
            <div class="mpage__ledger-head">
              <strong>移轉 <span class="num">{{ no }}</span> · {{ LEDGER_LABELS[str(row, "kind")] ?? str(row, "kind") }}</strong>
              <span class="mpage__dim num">{{ formatDateTime(row.created_at) }}</span>
            </div>
            <ul class="mpage__entries">
              <li v-for="(e, i) in list<Rec>(row, 'entries')" :key="i">
                {{ walletTitle(findRow(ws, "wallets", e.wallet_id)) }}：
                <span class="num" :class="num(e, 'amount_minor') < 0 ? 'mpage__neg' : 'mpage__pos'">{{ formatSim(num(e, "amount_minor")) }}</span>
              </li>
            </ul>
          </li>
        </ol>
      </HudPanel>
    </div>

    <CommandDialog :form="form" />
  </div>
</template>

<style scoped src="../shared/page.css"></style>
