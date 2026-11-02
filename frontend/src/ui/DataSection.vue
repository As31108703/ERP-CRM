<script setup lang="ts" generic="T extends { id: string }">
import { computed, nextTick, ref, watch } from "vue";
import { matchesQuery, normalizeSearch, prefersReducedMotion } from "../lib/search";
import EmptyState from "./EmptyState.vue";
import HudPanel from "./HudPanel.vue";

const PAGE_SIZE = 12;
const QUERY_MAX = 120;

const props = withDefaults(
  defineProps<{
    title: string;
    items: readonly T[];
    searchText: (item: T) => string;
    statusOf: (item: T) => string;
    targetId?: string | null;
    statusLabel?: (status: string) => string;
    /** 世代或紀錄種類改變時換一個值，搜尋、篩選與頁碼會重設。 */
    resetKey?: string;
    emptyText?: string;
    code?: string;
  }>(),
  {
    targetId: null,
    statusLabel: (s: string) => s,
    resetKey: "",
    emptyText: "還沒有紀錄。",
    code: "",
  },
);

const emit = defineEmits<{ "clear-target": [] }>();
defineSlots<{
  item(props: { item: T; targeted: boolean }): unknown;
  actions?(props: Record<string, never>): unknown;
}>();

const query = ref("");
const status = ref("");
const page = ref(0);
const listEl = ref<HTMLElement | null>(null);
const uid = `ds-${Math.random().toString(36).slice(2, 8)}`;

const indexed = computed(() => props.items.map((item) => ({ item, text: normalizeSearch(props.searchText(item)) })));

const statuses = computed(() => {
  const seen: string[] = [];
  for (const item of props.items) {
    const s = props.statusOf(item);
    if (!seen.includes(s)) seen.push(s);
  }
  return seen;
});

const filtered = computed(() =>
  indexed.value
    .filter(({ item, text }) => (!status.value || props.statusOf(item) === status.value) && matchesQuery(text, query.value))
    .map(({ item }) => item),
);

const pageCount = computed(() => Math.max(1, Math.ceil(filtered.value.length / PAGE_SIZE)));
const currentPage = computed(() => Math.min(page.value, pageCount.value - 1));
const visible = computed(() => filtered.value.slice(currentPage.value * PAGE_SIZE, (currentPage.value + 1) * PAGE_SIZE));
const hasFilters = computed(() => query.value !== "" || status.value !== "");

/** 使用者改搜尋、篩選或頁碼時通知外層清除全域定位（F§2）。 */
function userChanged(): void {
  emit("clear-target");
}

function onQuery(event: Event): void {
  query.value = (event.target as HTMLInputElement).value.slice(0, QUERY_MAX);
  page.value = 0;
  userChanged();
}

function onStatus(event: Event): void {
  status.value = (event.target as HTMLSelectElement).value;
  page.value = 0;
  userChanged();
}

function goPage(delta: number): void {
  page.value = Math.min(pageCount.value - 1, Math.max(0, currentPage.value + delta));
  userChanged();
}

function clearFilters(): void {
  query.value = "";
  status.value = "";
  page.value = 0;
  userChanged();
}

watch(
  () => props.resetKey,
  () => {
    query.value = "";
    status.value = "";
    page.value = 0;
  },
);

/** 定位：清除搜尋與篩選、跳到紀錄所在頁、聚焦並捲到畫面中央。 */
watch(
  () => [props.targetId, props.items] as const,
  async ([id]) => {
    if (!id) return;
    const index = props.items.findIndex((item) => item.id === id);
    if (index < 0) return;
    query.value = "";
    status.value = "";
    page.value = Math.floor(index / PAGE_SIZE);
    await nextTick();
    // 以 dataset 比對而非組 CSS 選擇器：不依賴 CSS.escape（jsdom 與部分舊瀏覽器沒有），id 含特殊字元也安全。
    const card = Array.from(listEl.value?.querySelectorAll<HTMLElement>("[data-record-id]") ?? []).find(
      (el) => el.dataset.recordId === id,
    );
    if (!card) return;
    card.focus({ preventScroll: true });
    card.scrollIntoView?.({ block: "center", behavior: prefersReducedMotion() ? "auto" : "smooth" });
  },
  { immediate: true },
);
</script>

<template>
  <HudPanel :title="title" :code="code" class="data-section">
    <template #meta>
      <span class="data-section__total num">{{ items.length }}</span>
    </template>
    <template v-if="$slots.actions" #actions><slot name="actions" /></template>

    <div class="data-section__tools">
      <label class="field field--grow">
        <span class="field__label">搜尋</span>
        <input
          type="search"
          :value="query"
          :maxlength="QUERY_MAX"
          placeholder="輸入關鍵字，空白分隔多個條件"
          :aria-controls="`${uid}-list`"
          @input="onQuery"
        />
      </label>
      <label class="field">
        <span class="field__label">狀態</span>
        <select :value="status" @change="onStatus">
          <option value="">全部狀態</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ statusLabel(s) }}</option>
        </select>
      </label>
      <button type="button" class="btn btn--ghost" data-testid="clear-filters" :disabled="!hasFilters" @click="clearFilters">
        清除篩選
      </button>
    </div>

    <p class="data-section__count" aria-live="polite">
      顯示 <span class="num">{{ filtered.length }}</span>／<span class="num">{{ items.length }}</span> 筆
    </p>

    <EmptyState v-if="items.length === 0" title="尚無資料" :text="emptyText" />
    <EmptyState v-else-if="filtered.length === 0" title="沒有符合條件的紀錄" text="沒有符合目前搜尋或狀態篩選的紀錄。">
      <button type="button" class="btn" @click="clearFilters">清除篩選</button>
    </EmptyState>

    <ul v-else :id="`${uid}-list`" ref="listEl" class="data-section__list">
      <li
        v-for="item in visible"
        :key="item.id"
        :data-record-id="item.id"
        class="data-section__card"
        :class="{ 'is-target': item.id === targetId }"
        tabindex="-1"
      >
        <span v-if="item.id === targetId" class="data-section__target-badge">目前定位</span>
        <slot name="item" :item="item" :targeted="item.id === targetId" />
      </li>
    </ul>

    <nav v-if="filtered.length > PAGE_SIZE" class="data-section__pager" aria-label="分頁">
      <button type="button" class="btn btn--ghost" data-testid="page-prev" :disabled="currentPage === 0" @click="goPage(-1)">
        上一頁
      </button>
      <span>
        第 <span class="num">{{ currentPage + 1 }}</span>／<span class="num">{{ pageCount }}</span> 頁 · 每頁
        <span class="num">{{ PAGE_SIZE }}</span> 筆
      </span>
      <button
        type="button"
        class="btn btn--ghost"
        data-testid="page-next"
        :disabled="currentPage >= pageCount - 1"
        @click="goPage(1)"
      >
        下一頁
      </button>
    </nav>
  </HudPanel>
</template>

<style scoped>
.data-section__total {
  color: var(--accent);
}
.data-section__tools {
  display: flex;
  flex-wrap: wrap;
  gap: var(--gap);
  align-items: flex-end;
}
.field--grow {
  flex: 1 1 220px;
}
.data-section__count {
  margin: calc(var(--gap) * 0.75) 0;
  color: var(--ink-dim);
  font-size: 0.85rem;
}
.data-section__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: var(--gap);
}
.data-section__card {
  position: relative;
  padding: var(--pad);
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  transition: border-color var(--motion-fast), box-shadow var(--motion-fast);
}
.data-section__card:focus-visible,
.data-section__card.is-target {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 1px var(--accent), 0 0 18px var(--glow);
}
.data-section__target-badge {
  float: right;
  font-size: 0.75rem;
  letter-spacing: 0.08em;
  color: var(--accent);
}
.data-section__pager {
  display: flex;
  gap: var(--gap);
  align-items: center;
  justify-content: center;
  margin-top: var(--gap);
  color: var(--ink-dim);
}
</style>
