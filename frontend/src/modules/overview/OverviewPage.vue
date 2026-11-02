<script setup lang="ts">
import { computed } from "vue";
import { formatDateTime, formatSim } from "../../lib/format";
import { MODULE_USES, moduleLabel } from "../../lib/modules";
import { rowsOf } from "../../lib/records";
import { useUiStore } from "../../stores/ui";
import { useWorkspaceStore } from "../../stores/workspace";
import HudPanel from "../../ui/HudPanel.vue";
import FirstRunGuide from "./FirstRunGuide.vue";
import PinnedRecords from "./PinnedRecords.vue";
import RoleCenter from "./RoleCenter.vue";
import WorkQueue from "./WorkQueue.vue";

/** 工作總覽（F§1 overview）：上手引導、日常工作台、數據、釘選、待處理工作、已啟用功能與目前範本。 */
const store = useWorkspaceStore();
const ui = useUiStore();

const ws = computed(() => store.view?.workspace ?? null);
const template = computed(() => store.templates?.items.find((t) => t.id === ws.value?.industry) ?? null);
const subtitle = computed(() => {
  const name = template.value?.name ?? ws.value?.industry ?? "";
  return `${name}範本 · 已啟用 ${ws.value?.modules.length ?? 0} 個模組`;
});

function reportMinor(key: string): number {
  const v = store.view?.report?.[key];
  return typeof v === "number" && Number.isFinite(v) ? v : 0;
}

const metrics = computed(() => [
  { id: "customers", label: "客戶", value: String(rowsOf(ws.value, "customers").length), unit: "位" },
  { id: "orders", label: "訂單", value: String(rowsOf(ws.value, "orders").length), unit: "筆" },
  { id: "inventory", label: "庫存成本", value: formatSim(reportMinor("inventory_value_minor")), unit: "" },
  { id: "profit", label: "模擬毛利", value: formatSim(reportMinor("gross_profit_minor")), unit: "" },
]);

const retention = computed(() =>
  store.view?.expires_at
    ? `公開 SIM 試用 · 一段時間未使用會自動清除，目前期限：${formatDateTime(store.view.expires_at)}`
    : "自架工作區 · 無自動清除期限",
);
</script>

<template>
  <div v-if="ws" class="ov" data-testid="page-overview">
    <header class="ov__head">
      <p class="ov__code num" aria-hidden="true">BRIDGE · OVERVIEW · {{ String(ws.version).padStart(4, "0") }}</p>
      <h1 id="workspace-overview-heading" class="ov__title" tabindex="-1">{{ ws.company_name }}</h1>
      <p class="ov__sub">
        <span>{{ subtitle }}</span>
        <span class="badge badge--accent">SIM 獨立工作區</span>
      </p>
    </header>

    <FirstRunGuide />
    <RoleCenter />

    <details class="ov__more">
      <summary>更多數據與流程教學</summary>
      <div class="ov__more-body">
        <div class="ov__learn">
          <h3 class="ov-tile__title">流程教學</h3>
          <p class="ov-tile__text">跟著步驟完成一筆完整流程，每一步都由你確認。</p>
          <button type="button" class="btn" @click="ui.navigateModule('learning')">開始流程教學 →</button>
        </div>
        <dl class="ov__metrics">
          <div v-for="m in metrics" :key="m.id" class="ov__metric" :data-testid="`metric-${m.id}`">
            <dt>{{ m.label }}</dt>
            <dd class="num">{{ m.value }}<small v-if="m.unit"> {{ m.unit }}</small></dd>
          </div>
        </dl>
      </div>
    </details>

    <div class="ov__pair">
      <PinnedRecords />
      <WorkQueue />
    </div>

    <details class="ov__more">
      <summary>查看全部已啟用功能</summary>
      <ul class="ov-grid ov__modules">
        <li v-for="m in ws.modules" :key="m">
          <button type="button" class="ov-tile" data-testid="module-tile" @click="ui.navigateModule(m)">
            <span class="ov-tile__title">{{ moduleLabel(m) }}</span>
            <span class="ov-tile__text">{{ MODULE_USES[m] ?? "" }}</span>
          </button>
        </li>
      </ul>
    </details>

    <HudPanel title="目前範本" code="TPL-INFO">
      <p class="ov-tile__text">{{ template?.name ?? ws.industry }}範本。{{ retention }}</p>
      <div class="ov-row">
        <button type="button" class="btn" @click="ui.navigateModule('settings')">檢視設定與匯出</button>
        <button type="button" class="btn btn--ghost" @click="ui.navigateModule('capabilities')">查看功能地圖</button>
      </div>
    </HudPanel>
  </div>
</template>

<style scoped src="./overview.css"></style>
<style scoped>
.ov {
  display: grid;
  gap: calc(var(--gap) * 1.5);
}
.ov__code {
  margin: 0;
  font-size: 0.72rem;
  letter-spacing: 0.18em;
  color: var(--accent);
}
.ov__title {
  margin: 2px 0 4px;
  font-family: var(--font-display);
  font-size: 1.6rem;
  letter-spacing: 0.04em;
  outline: none;
  overflow-wrap: anywhere;
}
.ov__sub {
  margin: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  color: var(--ink-dim);
}
.ov__pair {
  display: grid;
  gap: calc(var(--gap) * 1.5);
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 420px), 1fr));
  align-items: start;
}
.ov__more {
  border: 1px solid var(--line);
  padding: 10px 14px;
  background: color-mix(in srgb, var(--surface) 70%, transparent);
}
.ov__more summary {
  cursor: pointer;
  font-weight: 600;
}
.ov__more-body,
.ov__modules {
  margin-top: 12px;
}
.ov__more-body {
  display: grid;
  gap: var(--gap);
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 260px), 1fr));
}
.ov__learn {
  display: grid;
  gap: 6px;
  align-content: start;
}
.ov__learn h3,
.ov__learn p {
  margin: 0;
}
.ov__learn .btn {
  justify-self: start;
}
.ov__metrics {
  margin: 0;
  display: grid;
  gap: 8px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}
.ov__metric {
  padding: 8px 10px;
  border-left: 2px solid var(--accent);
  background: color-mix(in srgb, var(--surface-2) 60%, transparent);
}
.ov__metric dt {
  font-size: 0.78rem;
  color: var(--ink-dim);
}
.ov__metric dd {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 600;
  overflow-wrap: anywhere;
}
</style>
