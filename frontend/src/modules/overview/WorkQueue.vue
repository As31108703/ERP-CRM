<script setup lang="ts">
import { computed, ref } from "vue";
import type { QueueItem } from "../../api/types";
import { useUiStore } from "../../stores/ui";
import { useWorkspaceStore } from "../../stores/workspace";
import HudPanel from "../../ui/HudPanel.vue";

/**
 * 待處理工作（F§2）：由後端依目前資料整理，需要先處理的排在前面。
 * 預設顯示 8 件，可展開其餘；點選只會前往紀錄，不會自動付款、出貨或更新資料。
 */
type Filter = "all" | "attention" | "next";

const VISIBLE = 8;
const FILTERS: { id: Filter; label: string }[] = [
  { id: "all", label: "全部" },
  { id: "attention", label: "需要先處理" },
  { id: "next", label: "可接續" },
];
const EMPTY: Record<Filter, string> = {
  all: "目前沒有需要接續的工作。建立客戶、訂單或任務後，這裡會列出下一步。",
  attention: "目前沒有需要先處理的工作，可以切回「全部」查看下一步。",
  next: "目前沒有可直接接續的工作，請先查看需要處理的項目。",
};

const store = useWorkspaceStore();
const ui = useUiStore();
const filter = ref<Filter>("all");
const expanded = ref(false);

const items = computed<QueueItem[]>(() => store.workbench?.queue ?? []);
const counts = computed(() => ({
  all: items.value.length,
  attention: items.value.filter((i) => i.priority === "attention").length,
  next: items.value.filter((i) => i.priority === "next").length,
}));
const filtered = computed(() => items.value.filter((i) => filter.value === "all" || i.priority === filter.value));
const visible = computed(() => (expanded.value ? filtered.value : filtered.value.slice(0, VISIBLE)));

function choose(next: Filter): void {
  filter.value = next;
  expanded.value = false;
}
</script>

<template>
  <HudPanel title="待處理工作" code="TASK-QUEUE" eyebrow="依目前資料整理 · 點選後再核對" data-testid="work-queue">
    <template #actions>
      <span class="badge num" data-testid="work-queue-count">{{ counts.all }} 件</span>
    </template>
    <div class="segmented wq__filters" role="group" aria-label="待處理工作範圍">
      <button
        v-for="f in FILTERS"
        :key="f.id"
        type="button"
        :data-testid="`work-queue-filter-${f.id}`"
        :aria-pressed="filter === f.id ? 'true' : 'false'"
        @click="choose(f.id)"
      >
        {{ f.label }} <span class="num">{{ counts[f.id] }}</span>
      </button>
    </div>
    <ol v-if="visible.length" class="wq__list">
      <li v-for="item in visible" :key="item.id">
        <button
          type="button"
          class="wq__item"
          data-testid="work-queue-item"
          :data-queue-id="item.id"
          :class="`wq__item--${item.priority}`"
          @click="ui.navigateTo(item.target)"
        >
          <span class="wq__label">{{ item.label }}</span>
          <span class="wq__copy">
            <strong>{{ item.title }}</strong>
            <small>{{ item.description }}</small>
          </span>
          <span aria-hidden="true">↗</span>
        </button>
      </li>
    </ol>
    <p v-else class="ov-empty" data-testid="work-queue-empty">{{ EMPTY[filter] }}</p>
    <button
      v-if="filtered.length > VISIBLE"
      type="button"
      class="btn btn--ghost btn--sm wq__more"
      data-testid="work-queue-more"
      :aria-expanded="expanded ? 'true' : 'false'"
      @click="expanded = !expanded"
    >
      {{ expanded ? "收合待處理工作" : `查看其餘 ${filtered.length - VISIBLE} 件工作` }}
    </button>
    <p class="ov-note">這份清單不會自動付款、出貨或更新資料，實際操作仍以伺服器檢查為準。</p>
  </HudPanel>
</template>

<style scoped src="./overview.css"></style>
<style scoped>
.wq__filters {
  margin-bottom: 12px;
}
.wq__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 6px;
}
.wq__item {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 8px 10px;
  text-align: left;
  font: inherit;
  color: var(--ink);
  background: color-mix(in srgb, var(--surface-2) 70%, transparent);
  border: 1px solid var(--line);
  cursor: pointer;
}
.wq__item:hover,
.wq__item:focus-visible {
  border-color: var(--accent);
}
.wq__label {
  font-size: 0.75rem;
  padding: 2px 8px;
  border: 1px solid var(--accent);
  color: var(--accent);
  white-space: nowrap;
}
.wq__item--attention .wq__label {
  border-color: var(--warn);
  color: var(--warn);
}
.wq__copy {
  display: grid;
  min-width: 0;
}
.wq__copy strong,
.wq__copy small {
  overflow-wrap: anywhere;
}
.wq__copy small {
  color: var(--ink-dim);
}
.wq__more {
  margin-top: 8px;
}
@media (max-width: 479.98px) {
  .wq__item {
    grid-template-columns: minmax(0, 1fr) auto;
  }
  .wq__label {
    grid-column: 1 / -1;
    justify-self: start;
  }
}
</style>
