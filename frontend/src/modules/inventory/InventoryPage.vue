<script setup lang="ts">
import { computed } from "vue";
import { formatSim, simInput } from "../../lib/format";
import { list, num, recordName, statusKey, statusLabel, str, type Rec, type Row } from "../../lib/records";
import DataSection from "../../ui/DataSection.vue";
import EmptyState from "../../ui/EmptyState.vue";
import RecordCard from "../../ui/RecordCard.vue";
import { API_V1, isError, readMoney, readQty, useCommandForm } from "../shared/commandForm";
import { availableOf, createBlocker, createSpec, moneyField } from "../shared/createForms";
import CommandDialog from "../shared/CommandDialog.vue";
import PageHead from "../shared/PageHead.vue";
import { usePage } from "../shared/usePage";

const { store, ws, resetKey, rows, enabled, readiness, targetId, clearTarget, searchText } = usePage();
const form = useCommandForm();

const products = computed(() => rows("products"));
const createReason = computed(() => createBlocker("product", ws.value));

const path = (p: Row, action = "") => `${API_V1}/inventory/products/${encodeURIComponent(p.id)}${action ? `/${action}` : ""}`;

function openReceive(p: Row): void {
  form.open({
    title: `採購入庫：${recordName(p, "商品")}`,
    fields: [
      {
        name: "quantity",
        label: "入庫數量",
        type: "number",
        min: 1,
        required: true,
        hint: `以目前採購成本 ${formatSim(num(p, "cost_minor"))} 計價，由商家錢包付給供應商`,
      },
    ],
    initial: { quantity: 1 },
    submitLabel: "確認入庫",
    build: (v) => {
      const qty = readQty(v, "quantity", "入庫數量");
      return isError(qty) ? qty.error : { method: "POST", path: path(p, "receive"), body: { quantity: qty } };
    },
  });
}

function openEdit(p: Row): void {
  form.open({
    title: "編輯商品",
    fields: [
      { name: "name", label: "商品名稱", required: true, maxlength: 100 },
      { name: "sku", label: "SKU", required: true },
      moneyField("price_minor", "售價（SIM）"),
      moneyField("cost_minor", "採購成本（SIM）", "只影響之後的採購入庫"),
    ],
    initial: {
      name: str(p, "name"),
      sku: str(p, "sku"),
      price_minor: simInput(num(p, "price_minor")),
      cost_minor: simInput(num(p, "cost_minor")),
    },
    build: (v) => {
      const price = readMoney(v, "price_minor", "售價", 1);
      if (isError(price)) return price.error;
      const cost = readMoney(v, "cost_minor", "採購成本", 0);
      if (isError(cost)) return cost.error;
      return { method: "PATCH", path: path(p), body: { name: v.name, sku: v.sku, price_minor: price, cost_minor: cost } };
    },
  });
}
</script>

<template>
  <div class="mpage" data-testid="page-inventory">
    <PageHead code="MODULE · INVENTORY · FIFO" title="商品庫存" lead="商品目錄與採購入庫；出貨依 FIFO 批次計算成本，可用量 = 現有 − 已保留。">
      <button
        type="button"
        class="btn btn--primary"
        data-testid="create-product"
        :disabled="Boolean(createReason) || store.busy"
        @click="form.open(createSpec('product', ws))"
      >
        新增商品
      </button>
      <span v-if="createReason" class="phead__reason">{{ createReason }}</span>
    </PageHead>

    <EmptyState v-if="!enabled('inventory')" title="尚未啟用此模組" text="請到設定頁切換產業範本或調整模組。" />
    <DataSection
      v-else
      title="商品"
      code="SKU-BAY"
      :items="products"
      :search-text="(p: Row) => searchText('product', p)"
      :status-of="(p: Row) => statusKey('product', p)"
      :status-label="statusLabel"
      :target-id="targetId('product')"
      :reset-key="resetKey"
      empty-text="還沒有商品。新增商品後再以採購入庫建立庫存。"
      @clear-target="clearTarget"
    >
      <template #item="{ item }">
        <RecordCard kind="product" :row="item" :readiness="readiness('product', item.id)">
          <template #title>
            {{ recordName(item, "商品") }}<span class="badge badge--accent mpage__sku num">{{ str(item, "sku") }}</span>
          </template>
          <template #meta>
            售價 <span class="num">{{ formatSim(num(item, "price_minor")) }}</span> · 成本
            <span class="num">{{ formatSim(num(item, "cost_minor")) }}</span>
          </template>
          <div class="mpage__tiles">
            <div class="mpage__tile" data-stock="available">
              <span class="mpage__tile-label">可用</span><span class="mpage__tile-value num">{{ availableOf(item) }}</span>
            </div>
            <div class="mpage__tile" data-stock="reserved">
              <span class="mpage__tile-label">保留</span><span class="mpage__tile-value num">{{ num(item, "reserved") }}</span>
            </div>
            <div class="mpage__tile" data-stock="on_hand">
              <span class="mpage__tile-label">現有</span><span class="mpage__tile-value num">{{ num(item, "on_hand") }}</span>
            </div>
          </div>
          <details class="mpage__expander">
            <summary>FIFO 成本批次（{{ list(item, "lots").length }}）</summary>
            <ol v-if="list(item, 'lots').length" class="mpage__lines">
              <li v-for="(lot, i) in list<Rec>(item, 'lots')" :key="i">
                <span class="num">{{ num(lot, "quantity") }} × {{ formatSim(num(lot, "cost_minor")) }}</span>
              </li>
            </ol>
            <p v-else class="mpage__dim">目前沒有庫存批次。</p>
          </details>
          <template #actions>
            <button type="button" class="btn btn--sm" :disabled="store.busy" @click="openReceive(item)">採購入庫</button>
            <button type="button" class="btn btn--sm" :disabled="store.busy" @click="openEdit(item)">編輯商品</button>
          </template>
        </RecordCard>
      </template>
    </DataSection>

    <CommandDialog :form="form" />
  </div>
</template>

<style scoped src="../shared/page.css"></style>
