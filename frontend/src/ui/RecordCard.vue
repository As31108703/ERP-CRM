<script setup lang="ts">
import { computed, ref } from "vue";
import { RouterLink } from "vue-router";
import type { TargetRef } from "../api/types";
import { LIFECYCLE_KINDS, type LifecycleKind } from "../lib/lifecycle";
import { moduleOfKind, statusKey, statusLabel, targetLocation, type Row } from "../lib/records";
import { useUiStore } from "../stores/ui";
import { useWorkspaceStore } from "../stores/workspace";
import LifecycleTrack from "./LifecycleTrack.vue";

export interface Readiness {
  summary: string;
  blockers: { message: string; target: TargetRef }[];
}

/**
 * 紀錄卡：標題列（標題、狀態、釘選）、生命週期軌道（有流程的單據）、內容與操作、
 * 操作條件提示（含「前往處理」）、「紀錄與來源」JSON 展開。
 * `readiness` 來自 GET /api/v1/workbench；尚未取得時為 null，不顯示提示區。
 */
const props = withDefaults(defineProps<{ kind: string; row: Row; readiness?: Readiness | null }>(), {
  readiness: null,
});

defineSlots<{
  title(props: Record<string, never>): unknown;
  meta?(props: Record<string, never>): unknown;
  default?(props: Record<string, never>): unknown;
  actions?(props: Record<string, never>): unknown;
}>();

const ui = useUiStore();
const store = useWorkspaceStore();
const pinError = ref("");

const lifecycleKind = computed(() =>
  Object.prototype.hasOwnProperty.call(LIFECYCLE_KINDS, props.kind) ? (props.kind as LifecycleKind) : null,
);
const showStatus = computed(() => props.kind === "product" || typeof props.row.status === "string");
const status = computed(() => statusKey(props.kind, props.row));
const pinned = computed(() => ui.isPinned(props.kind, props.row.id));
const json = computed(() => JSON.stringify(props.row, null, 2));

function togglePin(): void {
  const modules = store.view?.workspace?.modules ?? [];
  pinError.value =
    ui.togglePin({ module: moduleOfKind(props.kind, modules), kind: props.kind, id: props.row.id }) ?? "";
}
</script>

<template>
  <article class="rcard" :data-kind="kind">
    <header class="rcard__head">
      <div class="rcard__titles">
        <h3 class="rcard__title"><slot name="title" /></h3>
        <p v-if="$slots.meta" class="rcard__meta"><slot name="meta" /></p>
      </div>
      <span v-if="showStatus" class="badge" :class="{ 'badge--warn': status === 'cancelled' || status === 'inactive' }">
        {{ statusLabel(status) }}
      </span>
      <button
        type="button"
        class="btn btn--ghost btn--sm rcard__pin"
        :aria-pressed="pinned ? 'true' : 'false'"
        data-testid="pin-toggle"
        @click="togglePin"
      >{{ pinned ? "已釘選" : "釘選" }}</button>
    </header>
    <p v-if="pinError" class="rcard__pin-error" role="alert">{{ pinError }}</p>

    <LifecycleTrack v-if="lifecycleKind" :kind="lifecycleKind" :row="row" />

    <div v-if="$slots.default" class="rcard__body"><slot /></div>
    <div v-if="$slots.actions" class="rcard__actions"><slot name="actions" /></div>

    <div v-if="readiness" class="rcard__ready" data-testid="readiness">
      <p class="rcard__ready-summary"><span class="rcard__ready-tag num" aria-hidden="true">NEXT</span>{{ readiness.summary }}</p>
      <ul v-if="readiness.blockers.length" class="rcard__blockers">
        <li v-for="(b, i) in readiness.blockers" :key="i">
          <span>{{ b.message }}</span>
          <RouterLink :to="targetLocation(b.target)" class="rcard__go" data-testid="readiness-go">前往處理 ↗</RouterLink>
        </li>
      </ul>
    </div>

    <details class="rcard__details">
      <summary>紀錄與來源</summary>
      <pre class="num">{{ json }}</pre>
    </details>
  </article>
</template>

<style scoped>
.rcard {
  display: grid;
  gap: calc(var(--gap) * 0.75);
}
.rcard__head {
  display: flex;
  align-items: flex-start;
  gap: var(--gap);
}
.rcard__titles {
  flex: 1;
  min-width: 0;
}
.rcard__title {
  margin: 0;
  font-size: 1rem;
  overflow-wrap: anywhere;
}
.rcard__meta {
  margin: 2px 0 0;
  color: var(--ink-dim);
  font-size: 0.85rem;
}
.rcard__pin[aria-pressed="true"] {
  --btn-c: var(--accent);
  color: var(--accent);
}
.rcard__pin-error {
  margin: 0;
  color: var(--danger);
  font-size: 0.85rem;
}
.rcard__body {
  display: grid;
  gap: 6px;
}
.rcard__body :deep(p) {
  margin: 0;
}
.rcard__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.rcard__ready {
  padding: 8px 10px;
  border-left: 2px solid var(--accent);
  background: color-mix(in srgb, var(--accent) 7%, transparent);
  font-size: 0.85rem;
}
.rcard__ready-summary {
  margin: 0;
  display: flex;
  gap: 8px;
  align-items: baseline;
}
.rcard__ready-tag {
  font-size: 0.68rem;
  letter-spacing: 0.12em;
  color: var(--accent);
}
.rcard__blockers {
  margin: 6px 0 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 4px;
}
.rcard__blockers li {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  color: var(--warn);
}
.rcard__go {
  white-space: nowrap;
}
.rcard__details summary {
  cursor: pointer;
  color: var(--ink-dim);
  font-size: 0.8rem;
}
.rcard__details pre {
  margin: 6px 0 0;
  max-height: 280px;
  overflow: auto;
  padding: 8px;
  font-size: 0.75rem;
  background: var(--bg-deep);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
}
</style>
