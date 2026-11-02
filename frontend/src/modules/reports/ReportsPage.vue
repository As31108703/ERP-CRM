<script setup lang="ts">
import { computed } from "vue";
import { formatSim } from "../../lib/format";
import { num, rowsOf } from "../../lib/records";
import { useWorkspaceStore } from "../../stores/workspace";
import EmptyState from "../../ui/EmptyState.vue";
import Gauge from "../../ui/Gauge.vue";
import HudPanel from "../../ui/HudPanel.vue";
import PageHead from "../shared/PageHead.vue";

/** 報表數字全部由後端 report(w) 計算；量表比率由目前快照加總（只用於呈現）。 */
const METRIC_LABELS: Record<string, string> = {
  sales_minor: "模擬出貨金額",
  refunds_minor: "模擬退貨金額",
  cost_of_goods_sold_minor: "FIFO 出貨成本",
  gross_profit_minor: "FIFO 模擬毛利",
  estimated_gross_profit_minor: "目錄成本估算毛利",
  inventory_value_minor: "庫存價值",
  service_payments_minor: "服務測試幣收款",
};

const ADMIN_LABELS: Record<string, string> = {
  active_units: "啟用中的單位",
  active_staff: "在職假員工",
  scheduled_shifts: "已排定班次",
  actual_work_minutes: "實際工時（分鐘）",
  open_requests: "未結案申請",
  prepared_unreviewed_requests: "已備妥待審申請",
  available_equipment: "可借用設備",
  active_reservations: "借用中預約",
  pinned_notices: "置頂公告",
};

const store = useWorkspaceStore();
const ws = computed(() => store.view?.workspace ?? null);
const report = computed(() => (store.view?.report ?? null) as Record<string, unknown> | null);

const metrics = computed(() => {
  const r = report.value;
  if (!r) return [];
  const known = Object.keys(METRIC_LABELS).filter((k) => typeof r[k] === "number");
  const extra = Object.keys(r).filter((k) => k.endsWith("_minor") && !(k in METRIC_LABELS) && typeof r[k] === "number");
  return [...known, ...extra].map((key) => ({ key, label: METRIC_LABELS[key] ?? key, value: r[key] as number }));
});

const admin = computed(() => {
  const a = report.value?.administration;
  if (!a || typeof a !== "object") return [];
  return Object.entries(a as Record<string, unknown>)
    .filter(([, v]) => typeof v === "number")
    .map(([key, value]) => ({ key, label: ADMIN_LABELS[key] ?? key, value: value as number }));
});

const basis = computed(() => {
  const b = report.value?.gross_profit_basis;
  return b === "actual_simulation_fifo" ? "實際 FIFO 批次成本" : typeof b === "string" ? b : "—";
});

const gauges = computed(() => {
  const products = rowsOf(ws.value, "products");
  const onHand = products.reduce((s, p) => s + num(p, "on_hand"), 0);
  const available = products.reduce((s, p) => s + Math.max(0, num(p, "on_hand") - num(p, "reserved")), 0);
  const orders = rowsOf(ws.value, "orders").filter((o) => o.status !== "cancelled");
  const orderTotal = orders.reduce((s, o) => s + num(o, "total_minor"), 0);
  const orderPaid = orders.reduce((s, o) => s + num(o, "paid_minor"), 0);
  const services = rowsOf(ws.value, "services").filter((x) => x.status !== "cancelled");
  const serviceTotal = services.reduce((s, x) => s + num(x, "amount_minor"), 0);
  const servicePaid = services.reduce((s, x) => s + num(x, "paid_minor"), 0);
  return [
    { id: "stock", label: "庫存可用率", value: available, max: onHand, caption: `${available}／${onHand} 件` },
    { id: "orders", label: "訂單付款率", value: orderPaid, max: orderTotal, caption: `${formatSim(orderPaid)}／${formatSim(orderTotal)}` },
    { id: "services", label: "服務收款率", value: servicePaid, max: serviceTotal, caption: `${formatSim(servicePaid)}／${formatSim(serviceTotal)}` },
  ];
});
</script>

<template>
  <div class="mpage" data-testid="page-reports">
    <PageHead code="ANALYTICS · REPORT · SIM" title="模擬報表" lead="依目前工作區的模擬紀錄即時計算，金額皆為 SIM 測試幣，僅供練習核對。" />

    <HudPanel title="營運量表" code="GAUGE-01">
      <div class="rpt__gauges">
        <div v-for="g in gauges" :key="g.id" :data-gauge="g.id">
          <Gauge :label="g.label" :value="g.value" :max="g.max" :caption="g.caption" />
        </div>
      </div>
    </HudPanel>

    <EmptyState v-if="!report" title="尚未取得報表" text="請按「重新讀取」取得最新的工作區狀態。" />
    <template v-else>
      <HudPanel title="金額指標" code="METRIC-02">
        <dl class="rpt__metrics">
          <div v-for="m in metrics" :key="m.key" class="mpage__tile" :data-metric="m.key">
            <dt class="mpage__tile-label">{{ m.label }}</dt>
            <dd class="mpage__tile-value num">{{ formatSim(m.value) }}</dd>
          </div>
        </dl>
      </HudPanel>

      <HudPanel v-if="admin.length" title="行政概況" code="ADM-03">
        <dl class="rpt__metrics">
          <div v-for="m in admin" :key="m.key" class="mpage__tile">
            <dt class="mpage__tile-label">{{ m.label }}</dt>
            <dd class="mpage__tile-value num">{{ m.value }}</dd>
          </div>
        </dl>
      </HudPanel>

      <HudPanel title="核對依據" code="AUDIT-04">
        <ul class="rpt__notes">
          <li>模擬出貨金額＝各訂單品項售價 × 已出貨數量；模擬退貨金額＝售價 × 已退貨數量。</li>
          <li>FIFO 出貨成本依出貨時實際扣用的成本批次計算（扣除已退回的數量）；毛利依據：{{ basis }}。</li>
          <li>目錄成本估算毛利改用下單當時的商品目錄成本，可與 FIFO 毛利對照差異。</li>
          <li>庫存價值＝各商品剩餘成本批次的合計；製造完工只在商品間轉移成本，不移動測試幣。</li>
          <li>服務測試幣收款＝各服務已收取的測試幣合計。所有數字都不是真實財務資料。</li>
        </ul>
      </HudPanel>
    </template>
  </div>
</template>

<style scoped src="../shared/page.css"></style>
<style scoped>
.rpt__gauges {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: var(--gap);
}
.rpt__metrics {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 200px), 1fr));
  gap: 8px;
  margin: 0;
}
.rpt__metrics dd {
  margin: 0;
}
.rpt__notes {
  margin: 0;
  padding-left: 1.2em;
  display: grid;
  gap: 6px;
  color: var(--ink-dim);
  font-size: 0.9rem;
}
</style>
