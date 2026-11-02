<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { get } from "../../api/client";
import type { FirstRun, FirstRunItem, FirstRunRoute } from "../../api/types";
import { useUiStore } from "../../stores/ui";
import { useWorkspaceStore } from "../../stores/workspace";
import Gauge from "../../ui/Gauge.vue";
import HudPanel from "../../ui/HudPanel.vue";
import StepProgress from "../../ui/StepProgress.vue";

/**
 * 上手引導（F§4）：三項進度與起點路線由後端依實際紀錄判斷（開啟頁面不算完成）。
 * 收合狀態依工作區世代存在 `erpcrm.first-run.v1.<gen>`；工作區版本變動時重新讀取進度。
 */
const FIRST_RUN_API = "/api/v1/workbench/first-run";

const store = useWorkspaceStore();
const ui = useUiStore();

const data = ref<FirstRun | null>(null);
const failed = ref(false);
const heading = ref<HTMLElement | null>(null);
const reopen = ref<HTMLButtonElement | null>(null);

function isItem(v: unknown): v is FirstRunItem {
  const r = v as Record<string, unknown> | null;
  return !!r && typeof r.id === "string" && typeof r.label === "string" && typeof r.done === "boolean";
}

function isRoute(v: unknown): v is FirstRunRoute {
  const r = v as Record<string, unknown> | null;
  return !!r && ["module", "title", "description", "action"].every((k) => typeof r[k] === "string");
}

/** 只接受合約內的欄位；格式不符的部分當作未提供。 */
function normalize(raw: unknown): FirstRun | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  return {
    progress: Array.isArray(r.progress) ? r.progress.filter(isItem) : [],
    route: isRoute(r.route) ? r.route : null,
    learning_available: typeof r.learning_available === "number" ? r.learning_available : undefined,
  };
}

let seq = 0;
async function load(): Promise<void> {
  if (!store.view?.workspace) return;
  const mine = ++seq;
  try {
    const raw = await get<unknown>(FIRST_RUN_API);
    if (mine !== seq) return;
    data.value = normalize(raw);
    failed.value = data.value === null;
  } catch {
    // 端點尚未提供（404）或暫時失敗：只隱藏進度，入口仍可使用；錯誤不蓋過全域通知。
    if (mine !== seq) return;
    data.value = null;
    failed.value = true;
  }
}

watch(
  () => [store.view?.workspace?.generation_id, store.view?.version] as const,
  () => void load(),
  { immediate: true },
);

const progress = computed(() => data.value?.progress ?? []);
const doneCount = computed(() => progress.value.filter((p) => p.done).length);
/** StepProgress 是循序呈現：目前步驟為第一個尚未完成的項目。 */
const current = computed(() => {
  const i = progress.value.findIndex((p) => !p.done);
  return i < 0 ? progress.value.length : i;
});
const route = computed(() => data.value?.route ?? null);
/** 讀不到上手進度時入口照常顯示；有數字時只在可用路線數 > 0 時顯示。 */
const learning = computed(() => {
  const count = data.value?.learning_available;
  return count === undefined || count > 0;
});

async function show(visible: boolean): Promise<void> {
  ui.setFirstRunHidden(!visible);
  await nextTick();
  (visible ? heading.value : reopen.value)?.focus();
}
</script>

<template>
  <div v-if="ui.firstRunHidden" class="fr__collapsed">
    <span>工作台已就緒，可從左側選擇要做的工作。</span>
    <button ref="reopen" type="button" class="btn btn--sm" data-testid="first-run-reopen" @click="show(true)">開啟上手引導</button>
  </div>
  <HudPanel v-else tone="accent" code="BOOT-SEQ" eyebrow="你的系統已建立" data-testid="first-run-guide">
    <template #actions>
      <button type="button" class="btn btn--ghost btn--sm" data-testid="first-run-hide" @click="show(false)">收起引導</button>
    </template>
    <h2 ref="heading" class="fr__title" tabindex="-1">接下來，先完成一件工作。</h2>
    <p class="ov-tile__text">下面的按鈕會直接帶你到操作畫面。示範資料都可以修改，所有金額都是 SIM 測試幣。</p>

    <div v-if="progress.length" class="fr__progress">
      <Gauge :value="doneCount" :max="progress.length" label="上手進度" :caption="`${doneCount}／${progress.length}`" />
      <div class="fr__steps">
        <StepProgress :steps="progress.map((p) => p.label)" :current="current" label="上手進度" />
        <ul class="fr__items">
          <li
            v-for="p in progress"
            :key="p.id"
            :data-testid="`first-run-item-${p.id}`"
            :data-done="p.done ? 'true' : 'false'"
            :class="{ 'is-done': p.done }"
          >
            <span aria-hidden="true">{{ p.done ? "✓" : "○" }}</span>
            {{ p.label }}<span class="sr-only">{{ p.done ? "（已完成）" : "（尚未完成）" }}</span>
          </li>
        </ul>
      </div>
    </div>
    <p v-else-if="failed" class="ov-empty">上手進度暫時無法取得，仍可從下方入口開始。</p>

    <ul class="ov-grid fr__cards">
      <li v-if="route" class="fr__card">
        <h3 class="ov-tile__title">{{ route.title }}</h3>
        <p class="ov-tile__text">{{ route.description }}</p>
        <button type="button" class="btn btn--primary" data-testid="first-run-start" @click="ui.navigateModule(route.module)">
          {{ route.action }} →
        </button>
      </li>
      <li class="fr__card">
        <template v-if="learning">
          <h3 class="ov-tile__title">跟著做一筆完整流程</h3>
          <p class="ov-tile__text">畫面會提示庫存、測試幣與交付條件；每一步都由你確認。</p>
          <button type="button" class="btn" data-testid="first-run-learning" @click="ui.navigateModule('learning')">帶我做一次 →</button>
        </template>
        <template v-else>
          <h3 class="ov-tile__title">從已啟用的功能開始</h3>
          <p class="ov-tile__text">目前的功能沒有適用的流程教學，操作條件會顯示在各筆紀錄旁。</p>
          <button
            type="button"
            class="btn"
            data-testid="first-run-module"
            :disabled="!route"
            @click="route && ui.navigateModule(route.module)"
          >
            查看操作畫面 →
          </button>
        </template>
      </li>
      <li class="fr__card">
        <h3 class="ov-tile__title">把練習保存下來</h3>
        <p class="ov-tile__text">到設定頁匯出 SIM 備份；公開試用會到期清除，需要長期保留可下載本機啟動包。</p>
        <button type="button" class="btn" data-testid="first-run-settings" @click="ui.navigateModule('settings')">查看備份與設定 →</button>
      </li>
    </ul>
    <p class="ov-note">
      進度依目前工作區的實際紀錄更新，開啟頁面不會標記完成。<template v-if="ui.prefsVolatile">瀏覽器儲存無法使用，引導的顯示設定只保留在本分頁。</template>
    </p>
  </HudPanel>
</template>

<style scoped src="./overview.css"></style>
<style scoped>
.fr__collapsed {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px 12px;
  padding: 10px 14px;
  border: 1px dashed var(--line-strong);
  color: var(--ink-dim);
}
.fr__title {
  margin: 0 0 4px;
  font-family: var(--font-display);
  font-size: 1.25rem;
  outline: none;
}
.fr__progress {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: var(--gap);
  align-items: center;
  margin: 14px 0;
}
.fr__steps {
  display: grid;
  gap: 8px;
  min-width: 0;
}
.fr__items {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 4px 16px;
  font-size: 0.85rem;
  color: var(--ink-dim);
}
.fr__items .is-done {
  color: var(--ok);
}
.fr__card {
  display: grid;
  gap: 6px;
  align-content: start;
  padding: 12px;
  border: 1px solid var(--line);
  background: color-mix(in srgb, var(--surface-2) 50%, transparent);
}
.fr__card h3 {
  margin: 0;
}
.fr__card p {
  margin: 0;
}
.fr__card .btn {
  justify-self: start;
}
@media (max-width: 559.98px) {
  .fr__progress {
    grid-template-columns: minmax(0, 1fr);
    justify-items: center;
  }
}
</style>
