<script setup lang="ts">
import { computed } from "vue";
import { formatSim } from "../../lib/format";
import { findRow, list, num, recordName, statusKey, statusLabel, str, type Rec, type Row } from "../../lib/records";
import DataSection from "../../ui/DataSection.vue";
import EmptyState from "../../ui/EmptyState.vue";
import type { FormField } from "../../ui/FormDialog.vue";
import RecordCard from "../../ui/RecordCard.vue";
import { API_V1, isError, readQty, useCommandForm, type CommandFormSpec } from "../shared/commandForm";
import CommandDialog from "../shared/CommandDialog.vue";
import { bomLabel as sharedBomLabel, options, workOrderSpec as createWorkOrderSpec } from "../shared/createForms";
import PageHead from "../shared/PageHead.vue";
import { usePage } from "../shared/usePage";

const { store, ws, resetKey, rows, enabled, readiness, targetId, clearTarget, searchText } = usePage();
const form = useCommandForm();

const products = computed(() => rows("products"));
const boms = computed(() => rows("boms"));
const workOrders = computed(() => rows("work_orders"));

const bomReason = computed(() => (products.value.length < 2 ? "至少需要兩項商品（成品與材料）" : null));
const workOrderReason = computed(() => (boms.value.length === 0 ? "先建立 BOM 配方" : null));

function productName(id: unknown): string {
  return recordName(findRow(ws.value, "products", id), "商品");
}

function bomLabel(bom: Rec): string {
  return sharedBomLabel(ws.value, bom);
}

function bomSpec(): CommandFormSpec {
  const all = products.value;
  return {
    title: "建立 BOM 配方",
    fields: [
      { name: "product_id", label: "成品", type: "select", required: true, options: options(all, "商品") },
      ...all.map(
        (p): FormField => ({ name: `qty:${p.id}`, label: `${recordName(p, "商品")} 每件用量`, type: "number", min: 0 }),
      ),
    ],
    initial: Object.fromEntries(all.map((p) => [`qty:${p.id}`, 0])),
    submitLabel: "建立 BOM",
    build: (v) => {
      const components: { product_id: string; quantity: number }[] = [];
      for (const p of all) {
        const qty = readQty(v, `qty:${p.id}`, `${recordName(p, "商品")} 每件用量`, 0);
        if (isError(qty)) return qty.error;
        if (qty > 0) components.push({ product_id: p.id, quantity: qty });
      }
      if (components.length === 0) return "請至少設定一項材料的每件用量。";
      if (components.some((c) => c.product_id === v.product_id)) return "成品不能是自己的材料。";
      return { method: "POST", path: `${API_V1}/manufacturing/boms`, body: { product_id: v.product_id, components } };
    },
  };
}

function workOrderSpec(): CommandFormSpec {
  return createWorkOrderSpec(ws.value);
}

const path = (w: Row, action: string) => `${API_V1}/manufacturing/work-orders/${encodeURIComponent(w.id)}/${action}`;

function rules(w: Row) {
  const status = str(w, "status");
  return {
    reserve: status === "planned",
    start: status === "reserved",
    complete: status === "started" || status === "in_progress",
    cancel: status !== "completed" && status !== "cancelled",
  };
}

function snapshotOf(w: Row): Rec | undefined {
  const snap = w.bom_snapshot;
  if (snap && typeof snap === "object") return snap as Rec;
  return findRow(ws.value, "boms", w.bom_id);
}

function workOrderTitle(w: Row): string {
  const index = workOrders.value.findIndex((x) => x.id === w.id) + 1;
  return `${productName(snapshotOf(w)?.product_id)} · 工單 ${index}`;
}

function bomSearch(b: Row): string {
  return searchText("bom", b, [bomLabel(b), ...list(b, "components").map((c) => productName(c.product_id))]);
}

function workOrderSearch(w: Row): string {
  return searchText("workOrder", w, [workOrderTitle(w)]);
}
</script>

<template>
  <div class="mpage" data-testid="page-manufacturing">
    <PageHead code="MODULE · FABRICATION · BOM" title="製造" lead="BOM 配方建立後不可修改，改版會產生新版本；工單依序備料、開工、完工入庫，材料成本以 FIFO 轉入成品，不移動任何測試幣。">
      <button
        type="button"
        class="btn"
        data-testid="create-bom"
        :disabled="Boolean(bomReason) || store.busy"
        @click="form.open(bomSpec())"
      >
        建立 BOM
      </button>
      <button
        type="button"
        class="btn btn--primary"
        data-testid="create-work-order"
        :disabled="Boolean(workOrderReason) || store.busy"
        @click="form.open(workOrderSpec())"
      >
        新增製造工單
      </button>
      <span v-if="bomReason || workOrderReason" class="phead__reason">{{ bomReason || workOrderReason }}</span>
    </PageHead>

    <EmptyState v-if="!enabled('manufacturing')" title="尚未啟用此模組" text="請到設定頁切換產業範本或調整模組。" />
    <div v-else class="mpage__grid">
      <DataSection
        title="BOM 配方"
        code="BOM-LIB"
        :items="boms"
        :search-text="bomSearch"
        :status-of="(b: Row) => statusKey('bom', b)"
        :status-label="statusLabel"
        :target-id="targetId('bom')"
        :reset-key="resetKey"
        empty-text="還沒有 BOM。先準備成品與材料兩項商品，再建立第一份配方。"
        @clear-target="clearTarget"
      >
        <template #item="{ item }">
          <RecordCard kind="bom" :row="item" :readiness="readiness('bom', item.id)">
            <template #title>{{ bomLabel(item) }}</template>
            <ul class="mpage__lines">
              <li v-for="c in list(item, 'components')" :key="str(c, 'product_id')">
                <strong>{{ productName(c.product_id) }}</strong>
                <span class="num">每件 × {{ num(c, "quantity") }}</span>
              </li>
            </ul>
          </RecordCard>
        </template>
      </DataSection>

      <DataSection
        title="製造工單"
        code="WO-LINE"
        :items="workOrders"
        :search-text="workOrderSearch"
        :status-of="(w: Row) => statusKey('workOrder', w)"
        :status-label="statusLabel"
        :target-id="targetId('workOrder')"
        :reset-key="resetKey"
        empty-text="還沒有工單。選一份 BOM 建立第一張製造工單。"
        @clear-target="clearTarget"
      >
        <template #item="{ item }">
          <RecordCard kind="workOrder" :row="item" :readiness="readiness('workOrder', item.id)">
            <template #title>{{ workOrderTitle(item) }}</template>
            <p class="mpage__money">
              製作 <span class="num">{{ num(item, "quantity") }}</span> 件
              <template v-if="typeof item.actual_cost_minor === 'number'">
                · 實際材料成本 <span class="num">{{ formatSim(num(item, "actual_cost_minor")) }}</span>
              </template>
            </p>
            <ul class="mpage__lines">
              <li v-for="c in list(snapshotOf(item), 'components')" :key="str(c, 'product_id')">
                <strong>{{ productName(c.product_id) }}</strong>
                <span class="num">需要 {{ num(c, "quantity") * num(item, "quantity") }} 件</span>
              </li>
            </ul>
            <details v-if="list(item, 'consumed_material_lots').length" class="mpage__expander">
              <summary>耗用材料批次</summary>
              <ul class="mpage__lines">
                <li v-for="(lot, i) in list(item, 'consumed_material_lots')" :key="i">
                  <strong>{{ productName(lot.product_id) }}</strong>
                  <span class="num">{{ num(lot, "quantity") }} × {{ formatSim(num(lot, "cost_minor")) }}</span>
                </li>
              </ul>
            </details>
            <template #actions>
              <button type="button" class="btn btn--sm" :disabled="!rules(item).reserve || store.busy" @click="form.direct('POST', path(item, 'reserve'))">
                備料
              </button>
              <button type="button" class="btn btn--sm" :disabled="!rules(item).start || store.busy" @click="form.direct('POST', path(item, 'start'))">
                開工
              </button>
              <button type="button" class="btn btn--sm" :disabled="!rules(item).complete || store.busy" @click="form.direct('POST', path(item, 'complete'))">
                完工入庫
              </button>
              <button type="button" class="btn btn--sm" :disabled="!rules(item).cancel || store.busy" @click="form.direct('POST', path(item, 'cancel'))">
                取消工單
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
