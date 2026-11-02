<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { ApiError, get } from "../../api/client";
import type { SearchItem, SearchResponse } from "../../api/types";
import { moduleLabel } from "../../lib/modules";
import { useUiStore } from "../../stores/ui";
import { useWorkspaceStore } from "../../stores/workspace";
import Dialog from "../../ui/Dialog.vue";

/**
 * 全域搜尋（F§2）：伺服器端比對（NFKC、小寫、折疊空白，每個詞都要命中），只含已啟用模組。
 * 每次 50 筆，可再載入；選擇結果只會前往紀錄，不執行任何操作。
 * 同時負責 Ctrl/Cmd+K：焦點在輸入元素、已有對話框或沒有工作區時不攔截。
 */
const PAGE = 50;
const QUERY_MAX = 120;
const DEBOUNCE_MS = 150;

const store = useWorkspaceStore();
const ui = useUiStore();

const open = computed(() => ui.searchOpen && store.hasWorkspace);
const query = ref("");
const items = ref<SearchItem[]>([]);
const total = ref(0);
const loading = ref(false);
const error = ref("");
const searched = ref("");
const input = ref<HTMLInputElement | null>(null);

const groups = computed(() => {
  const order: string[] = [];
  const by = new Map<string, SearchItem[]>();
  for (const item of items.value) {
    if (!by.has(item.module)) {
      by.set(item.module, []);
      order.push(item.module);
    }
    by.get(item.module)!.push(item);
  }
  return order.map((module) => ({ module, label: moduleLabel(module), items: by.get(module)! }));
});

let seq = 0;
let timer: ReturnType<typeof setTimeout> | null = null;

function searchUrl(q: string, offset: number): string {
  return `/api/v1/workbench/search?q=${encodeURIComponent(q)}&offset=${offset}&limit=${PAGE}`;
}

async function fetchPage(q: string, offset: number): Promise<void> {
  const mine = ++seq;
  loading.value = true;
  error.value = "";
  try {
    const res = await get<SearchResponse>(searchUrl(q, offset));
    if (mine !== seq) return;
    const page = Array.isArray(res?.items) ? res.items : [];
    items.value = offset === 0 ? page : [...items.value, ...page];
    total.value = typeof res?.total === "number" ? res.total : items.value.length;
    searched.value = q;
  } catch (err) {
    if (mine !== seq) return;
    error.value = err instanceof ApiError ? err.message : "搜尋暫時無法使用，請稍後再試。";
  } finally {
    if (mine === seq) loading.value = false;
  }
}

function reset(): void {
  seq += 1;
  if (timer) clearTimeout(timer);
  timer = null;
  items.value = [];
  total.value = 0;
  searched.value = "";
  loading.value = false;
  error.value = "";
}

function onInput(event: Event): void {
  query.value = (event.target as HTMLInputElement).value.slice(0, QUERY_MAX);
  const q = query.value.trim();
  reset();
  if (!q) return;
  timer = setTimeout(() => void fetchPage(q, 0), DEBOUNCE_MS);
}

function loadMore(): void {
  if (loading.value || !searched.value) return;
  void fetchPage(searched.value, items.value.length);
}

function choose(item: SearchItem): void {
  void ui.navigateTo({ module: item.module, kind: item.kind, id: item.id });
}

/** 開啟時清空並把焦點放到搜尋框（Dialog 預設會先聚焦關閉鈕，這裡在其後覆寫）。 */
watch(
  open,
  async (isOpen) => {
    if (!isOpen) return;
    query.value = "";
    reset();
    await nextTick();
    input.value?.focus();
  },
  { flush: "post" },
);

function typing(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    (target.isContentEditable || target.closest("input, textarea, select, [contenteditable='true']") !== null)
  );
}

function onKey(event: KeyboardEvent): void {
  if (!(event.ctrlKey || event.metaKey) || event.altKey || event.key.toLowerCase() !== "k") return;
  if (!store.hasWorkspace || typing(event.target)) return;
  if (document.querySelector("[data-erpcrm-dialog]")) return;
  event.preventDefault();
  ui.openSearch();
}

onMounted(() => document.addEventListener("keydown", onKey));
onBeforeUnmount(() => {
  document.removeEventListener("keydown", onKey);
  if (timer) clearTimeout(timer);
});
</script>

<template>
  <Dialog :open="open" title="搜尋工作區" code="SCAN · READ-ONLY" wide @close="ui.closeSearch()">
    <label class="field">
      <span class="sr-only">搜尋工作區紀錄</span>
      <input
        ref="input"
        type="search"
        class="gs__input"
        data-testid="search-input"
        aria-label="搜尋工作區紀錄"
        :maxlength="QUERY_MAX"
        placeholder="輸入客戶、商品、訂單或案件名稱"
        :value="query"
        @input="onInput"
      />
    </label>
    <div class="gs__results" aria-live="polite">
      <p v-if="!query.trim()" class="ov-empty">輸入關鍵字搜尋目前工作區。選擇結果只會帶你查看紀錄，不會執行任何操作。</p>
      <p v-else-if="error" class="gs__error" role="alert">{{ error }}</p>
      <p v-else-if="loading && !items.length" class="ov-empty">搜尋中…</p>
      <p v-else-if="searched && !items.length" class="ov-empty" data-testid="search-empty">
        沒有找到符合的紀錄。試試較短的名稱、商品編號或聯絡資訊。
      </p>
      <template v-else-if="items.length">
        <p class="ov-count" data-testid="search-count">顯示 {{ items.length }}／{{ total }} 筆結果，可縮小關鍵字以便查找。</p>
        <section v-for="g in groups" :key="g.module" class="gs__group" data-testid="search-group">
          <h3>{{ g.label }}</h3>
          <ul>
            <li v-for="item in g.items" :key="`${item.kind}:${item.id}`">
              <button
                type="button"
                class="gs__hit"
                data-testid="search-result"
                :data-record-id="item.id"
                :data-record-kind="item.kind"
                @click="choose(item)"
              >
                <strong>{{ item.title }}</strong>
                <span>{{ item.description }}</span>
                <small>{{ item.status_label || "查看紀錄" }} ↗</small>
              </button>
            </li>
          </ul>
        </section>
        <button
          v-if="items.length < total"
          type="button"
          class="btn btn--ghost btn--sm"
          data-testid="search-more"
          :disabled="loading"
          @click="loadMore"
        >
          載入更多搜尋結果
        </button>
      </template>
    </div>
    <template #footer>
      <span class="gs__foot"><kbd>Esc</kbd> 關閉搜尋</span>
      <span class="gs__foot">僅顯示已啟用模組的紀錄</span>
    </template>
  </Dialog>
</template>

<style scoped src="./overview.css"></style>
<style scoped>
.gs__input {
  width: 100%;
}
.gs__results {
  display: grid;
  gap: 10px;
  margin-top: 12px;
}
.gs__error {
  margin: 0;
  color: var(--danger);
}
.gs__group h3 {
  margin: 4px 0 6px;
  font-size: 0.8rem;
  letter-spacing: 0.08em;
  color: var(--accent);
}
.gs__group ul {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 4px;
}
.gs__hit {
  display: grid;
  gap: 2px;
  width: 100%;
  padding: 8px 10px;
  text-align: left;
  font: inherit;
  color: var(--ink);
  background: color-mix(in srgb, var(--surface-2) 70%, transparent);
  border: 1px solid var(--line);
  cursor: pointer;
}
.gs__hit:hover,
.gs__hit:focus-visible {
  border-color: var(--accent);
}
.gs__hit span,
.gs__hit strong {
  overflow-wrap: anywhere;
}
.gs__hit span,
.gs__hit small {
  color: var(--ink-dim);
  font-size: 0.82rem;
}
.gs__foot {
  margin-right: auto;
  font-size: 0.78rem;
  color: var(--ink-faint);
}
</style>
