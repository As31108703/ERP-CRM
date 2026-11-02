<script setup lang="ts">
import { computed, ref } from "vue";
import { useRouter } from "vue-router";
import { moduleLabel } from "../../lib/modules";
import { useWorkspaceStore } from "../../stores/workspace";
import EmptyState from "../../ui/EmptyState.vue";
import HudPanel from "../../ui/HudPanel.vue";
import StatusSignal from "../../ui/StatusSignal.vue";
import { blueprintTitle } from "../blueprint/blueprint";
import {
  CAPABILITIES,
  CAPABILITY_GROUPS,
  CAPABILITY_STATUS_LABELS,
  QUERY_MAX,
  REFERENCE_LINKS,
  capabilityDestination,
  destinationPath,
  filterCapabilities,
  type Capability,
  type CapabilityStatus,
} from "./capabilities";

const store = useWorkspaceStore();
const router = useRouter();

const query = ref("");
const group = ref("");
const status = ref<CapabilityStatus | "">("");

const STATUS_ORDER: CapabilityStatus[] = ["ready", "partial", "planned"];
const TONES: Record<CapabilityStatus, "ok" | "info" | "idle"> = { ready: "ok", partial: "info", planned: "idle" };

const counts = computed(() =>
  STATUS_ORDER.map((s) => ({ status: s, count: CAPABILITIES.filter((c) => c.status === s).length })),
);
const found = computed(() => filterCapabilities(query.value, group.value, status.value));
const hasFilters = computed(() => query.value !== "" || group.value !== "" || status.value !== "");
const modules = computed(() => store.view?.workspace?.modules ?? null);

function onQuery(event: Event): void {
  query.value = (event.target as HTMLInputElement).value.slice(0, QUERY_MAX);
}
function toggleStatus(s: CapabilityStatus): void {
  status.value = status.value === s ? "" : s;
}
function clearFilters(): void {
  query.value = "";
  group.value = "";
  status.value = "";
}

function requirementText(c: Capability): string {
  if (c.routes) return c.routes.map((r) => r.requires.map(moduleLabel).join("＋")).join("，或");
  return (c.requires ?? []).map(moduleLabel).join("、");
}

function destination(c: Capability): string | null {
  return capabilityDestination(c, modules.value);
}

function buttonText(c: Capability): string {
  const d = destination(c);
  if (d === "build" && c.module !== "build") return store.hasWorkspace ? "檢視另一套建置計畫" : "建立系統後使用";
  if (c.status === "partial") return "查看已實作部分";
  return "開啟功能";
}

function open(c: Capability): void {
  const d = destination(c);
  if (d) void router.push(destinationPath(d));
}
</script>

<template>
  <div class="capmap" data-testid="page-capabilities">
    <header class="capmap__head">
      <div>
        <p class="capmap__eyebrow num">CAPABILITY ATLAS · 34</p>
        <h1 class="capmap__title">先找到工作，再開啟功能</h1>
        <p class="capmap__lead">
          參考 Business Central、NetSuite 與 Odoo 常見的工作領域，標出星軌 ERP-CRM 目前做得到與尚待建置的範圍。
        </p>
      </div>
      <button
        type="button"
        class="btn"
        data-testid="capability-back"
        @click="router.push(store.hasWorkspace ? '/overview' : '/build')"
      >
        {{ store.hasWorkspace ? "回到工作總覽" : "開始建立我的系統" }}
      </button>
    </header>

    <p class="capmap__scope">
      「已可用」是指能以 SIM 測試資料完整操作，不代表與上述商用系統功能相同；所有金額都是測試幣，不連線真實金流、銀行、稅務或薪資。
    </p>

    <div class="capmap__counts" role="group" aria-label="依狀態篩選">
      <button
        v-for="c in counts"
        :key="c.status"
        type="button"
        class="capmap__count"
        :class="`is-${c.status}`"
        :aria-pressed="status === c.status"
        :data-status-filter="c.status"
        @click="toggleStatus(c.status)"
      >
        <span class="num capmap__count-n">{{ c.count }}</span>
        <span>{{ CAPABILITY_STATUS_LABELS[c.status] }}</span>
      </button>
    </div>

    <div class="capmap__filters">
      <label class="field capmap__search">
        <span class="field__label">搜尋功能</span>
        <input
          type="search"
          :value="query"
          :maxlength="QUERY_MAX"
          placeholder="例如：庫存、排班、CAP14"
          data-testid="capability-search"
          @input="onQuery"
        />
      </label>
      <label class="field">
        <span class="field__label">群組</span>
        <select v-model="group" data-testid="capability-group">
          <option value="">全部群組</option>
          <option v-for="g in CAPABILITY_GROUPS" :key="g" :value="g">{{ g }}</option>
        </select>
      </label>
      <label class="field">
        <span class="field__label">狀態</span>
        <select v-model="status" data-testid="capability-status">
          <option value="">全部狀態</option>
          <option v-for="s in STATUS_ORDER" :key="s" :value="s">{{ CAPABILITY_STATUS_LABELS[s] }}</option>
        </select>
      </label>
      <button type="button" class="btn btn--ghost" :disabled="!hasFilters" @click="clearFilters">清除篩選</button>
    </div>

    <p class="capmap__shown num" role="status" data-testid="capability-count">顯示 {{ found.length }}／{{ CAPABILITIES.length }} 項功能</p>

    <EmptyState v-if="found.length === 0" title="沒有符合的功能" text="換個關鍵字，或清除篩選看看。" />

    <ul v-else class="capmap__grid">
      <li v-for="c in found" :key="c.id" :data-capability="c.id">
        <HudPanel as="article" :title="c.title" :eyebrow="c.group" :code="c.id" :heading-level="2" class="capmap__card">
          <StatusSignal :tone="TONES[c.status]" :label="CAPABILITY_STATUS_LABELS[c.status]" />
          <p class="capmap__available">{{ c.available }}</p>
          <p class="capmap__gap"><strong>範圍與限制：</strong>{{ c.gap }}</p>
          <p v-if="requirementText(c)" class="capmap__requires"><strong>需要功能：</strong>{{ requirementText(c) }}</p>
          <div class="capmap__actions">
            <button v-if="destination(c)" type="button" class="btn btn--sm" @click="open(c)">{{ buttonText(c) }}</button>
            <RouterLink
              v-if="c.status === 'planned' || c.blueprint"
              class="capmap__blueprint"
              :to="c.blueprint ? { path: '/blueprint', query: { focus: c.blueprint } } : '/blueprint'"
            >
              查看擴充藍圖{{ c.blueprint ? `：${blueprintTitle(c.blueprint)}` : "" }} ↗
            </RouterLink>
          </div>
        </HudPanel>
      </li>
    </ul>

    <details class="capmap__refs">
      <summary>參考資料</summary>
      <ul>
        <li v-for="link in REFERENCE_LINKS" :key="link.href">
          <a :href="link.href" target="_blank" rel="noopener noreferrer">{{ link.label }}</a>
        </li>
      </ul>
    </details>
  </div>
</template>

<style scoped>
.capmap {
  display: grid;
  gap: var(--gap);
  max-width: 1280px;
}
.capmap__head {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: end;
  gap: var(--gap);
}
.capmap__eyebrow {
  margin: 0;
  font-size: 0.72rem;
  letter-spacing: 0.24em;
  color: var(--accent);
}
.capmap__title {
  margin: 4px 0;
  font-size: clamp(1.5rem, 3vw, 2.1rem);
  text-shadow: 0 0 18px var(--glow);
}
.capmap__lead,
.capmap__scope {
  margin: 0;
  max-width: 70ch;
  color: var(--ink-dim);
}
.capmap__scope {
  font-size: 0.85rem;
  border-left: 2px solid var(--warn);
  padding-left: 10px;
}
.capmap__counts {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.capmap__count {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 8px 14px;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  color: var(--ink);
  font: inherit;
  cursor: pointer;
}
.capmap__count[aria-pressed="true"] {
  border-color: var(--accent);
  box-shadow: 0 0 10px var(--glow);
}
.capmap__count-n {
  font-size: 1.4rem;
}
.capmap__count.is-ready .capmap__count-n {
  color: var(--ok);
}
.capmap__count.is-partial .capmap__count-n {
  color: var(--info);
}
.capmap__count.is-planned .capmap__count-n {
  color: var(--ink-faint);
}
.capmap__filters {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: end;
}
.capmap__search {
  flex: 1 1 240px;
}
.capmap__shown {
  margin: 0;
  font-size: 0.85rem;
  color: var(--ink-dim);
}
.capmap__grid {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: var(--gap);
}
.capmap__card {
  height: 100%;
}
.capmap__available {
  margin: 8px 0 4px;
}
.capmap__gap,
.capmap__requires {
  margin: 4px 0;
  font-size: 0.85rem;
  color: var(--ink-dim);
}
.capmap__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin-top: 8px;
}
.capmap__blueprint {
  font-size: 0.85rem;
  color: var(--accent);
}
.capmap__refs summary {
  cursor: pointer;
  color: var(--ink-dim);
}
.capmap__refs a {
  color: var(--accent);
}
</style>
