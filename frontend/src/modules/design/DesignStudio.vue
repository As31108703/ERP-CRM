<script setup lang="ts">
import { computed, nextTick, ref } from "vue";
import { useRouter } from "vue-router";
import type { LifecycleKind } from "../../lib/lifecycle";
import { LIFECYCLE_KINDS } from "../../lib/lifecycle";
import { matchesQuery, normalizeSearch } from "../../lib/search";
import { usePreferencesStore, type Density, type SchemePref } from "../../stores/preferences";
import {
  CATEGORY_LABELS,
  PANEL_STYLE_LABELS,
  THEMES,
  themeById,
  type ThemeCategory,
  type ThemeDef,
  type ThemeId,
} from "../../themes/themes";
import EmptyState from "../../ui/EmptyState.vue";
import Gauge from "../../ui/Gauge.vue";
import HudPanel from "../../ui/HudPanel.vue";
import LifecycleTrack from "../../ui/LifecycleTrack.vue";
import ProgressBar from "../../ui/ProgressBar.vue";
import StatusSignal from "../../ui/StatusSignal.vue";
import StepProgress from "../../ui/StepProgress.vue";
import ThemeThumb from "./ThemeThumb.vue";

const QUERY_MAX = 100;
const FEATURED: ThemeId[] = ["bridge", "quantum", "foundry"];

const prefs = usePreferencesStore();
const router = useRouter();

const applied = computed(() => prefs.theme);
const featuredId = ref<ThemeId>(FEATURED.includes(prefs.themeId) ? prefs.themeId : "bridge");
const featured = computed(() => themeById(featuredId.value));

// ── 圖庫篩選 ──
const category = ref<ThemeCategory | "all">("all");
const query = ref("");

const categories = computed(() => {
  const keys = Object.keys(CATEGORY_LABELS) as ThemeCategory[];
  return [
    { value: "all" as const, label: "全部主題", count: THEMES.length },
    ...keys.map((k) => ({ value: k, label: CATEGORY_LABELS[k], count: THEMES.filter((t) => t.category === k).length })),
  ];
});

function haystack(t: ThemeDef): string {
  return normalizeSearch(
    [t.name, t.englishName, t.description, t.signature, ...t.tags, CATEGORY_LABELS[t.category], PANEL_STYLE_LABELS[t.panelStyle]].join(" "),
  );
}

const shown = computed(() =>
  THEMES.filter((t) => (category.value === "all" || t.category === category.value) && matchesQuery(haystack(t), query.value)),
);
const hasFilters = computed(() => category.value !== "all" || query.value !== "");

function onQuery(event: Event): void {
  query.value = (event.target as HTMLInputElement).value.slice(0, QUERY_MAX);
}
function clearFilters(): void {
  category.value = "all";
  query.value = "";
}

// ── 試看與套用 ──
function isApplied(t: ThemeDef): boolean {
  return prefs.themeId === t.id;
}
function isPreviewing(t: ThemeDef): boolean {
  return prefs.previewId === t.id;
}
function applyLabel(t: ThemeDef): string {
  if (!isApplied(t)) return "套用這套";
  return prefs.previewing ? "回到這套" : "已套用";
}

async function focusCard(id: ThemeId, selector: string): Promise<void> {
  await nextTick();
  document.querySelector<HTMLElement>(`[data-theme-card="${id}"] ${selector}`)?.focus();
}

function preview(t: ThemeDef): void {
  prefs.previewTheme(t.id);
}

function applyOrReturn(t: ThemeDef): void {
  if (isApplied(t)) {
    prefs.cancelPreview();
  } else {
    prefs.applyTheme(t.id);
  }
  void focusCard(t.id, "[data-action=preview]");
}

function seeInWorkbench(t: ThemeDef): void {
  if (!isApplied(t)) prefs.previewTheme(t.id);
  prefs.keepPreviewForNextNavigation();
  void router.push("/overview");
}

const SCHEME_OPTIONS: { value: SchemePref; label: string }[] = [
  { value: "system", label: "跟隨系統" },
  { value: "light", label: "日間艦橋" },
  { value: "dark", label: "夜間" },
];
const DENSITY_OPTIONS: { value: Density; label: string }[] = [
  { value: "comfortable", label: "舒適" },
  { value: "compact", label: "緊湊" },
];

// ── 元件樣本（示範資料，不連 API） ──
const SAMPLE_ROWS: { kind: LifecycleKind; row: Record<string, unknown>; note: string }[] = [
  { kind: "order", row: { status: "paid", paid_minor: 12000, total_minor: 12000 }, note: "已付清，待出貨" },
  { kind: "order", row: { status: "cancelled", paid_minor: 0, total_minor: 4000, refunded_minor: 4000 }, note: "付清後取消" },
  { kind: "service", row: { status: "submitted" }, note: "交付待驗收" },
  { kind: "workOrder", row: { status: "reserved" }, note: "材料已預留" },
  { kind: "quote", row: { status: "issued" }, note: "已發出，等待確認" },
  { kind: "request", row: { status: "withdrawn", transitions: [{ status: "draft" }, { status: "submitted" }, { status: "withdrawn" }] }, note: "送出後撤回" },
];
const BUILD_STEPS = ["選擇產業", "命名公司", "挑選模組", "確認建立"];
</script>

<template>
  <div class="studio" data-testid="page-design">
    <header class="studio__head">
      <div>
        <p class="studio__eyebrow num">THEME BAY · 06</p>
        <h1 class="studio__title">主題圖庫</h1>
        <p class="studio__lead">
          六套原創星軌主題，各自有配色、標題字體與面板造型。可以先試看，確認後再套用；試看期間所有資料操作都會暫停。
        </p>
      </div>
      <div class="studio__current">
        <StatusSignal tone="ok" :label="`目前套用：${applied.name}`" />
        <StatusSignal v-if="prefs.previewThemeDef" tone="warn" pulse :label="`試看中：${prefs.previewThemeDef.name}`" />
        <div class="studio__prefs">
          <div class="segmented" role="group" aria-label="配色">
            <button v-for="o in SCHEME_OPTIONS" :key="o.value" type="button" :aria-pressed="prefs.scheme === o.value" @click="prefs.setScheme(o.value)">
              {{ o.label }}
            </button>
          </div>
          <div class="segmented" role="group" aria-label="密度">
            <button v-for="o in DENSITY_OPTIONS" :key="o.value" type="button" :aria-pressed="prefs.density === o.value" @click="prefs.setDensity(o.value)">
              {{ o.label }}
            </button>
          </div>
        </div>
        <p v-if="!prefs.persisted" class="studio__volatile">瀏覽器儲存無法使用，外觀目前只保留在本分頁。</p>
      </div>
    </header>

    <!-- 精選 -->
    <HudPanel class="studio__featured" eyebrow="精選主題" :title="featured.name" code="FTR-01" tone="accent">
      <template #actions>
        <div class="segmented" role="group" aria-label="切換精選主題">
          <button v-for="id in FEATURED" :key="id" type="button" :aria-pressed="featuredId === id" @click="featuredId = id">
            {{ themeById(id).name }}
          </button>
        </div>
      </template>
      <div class="studio__featured-body">
        <ThemeThumb :theme="featured" />
        <div class="studio__featured-copy">
          <p class="studio__english num">{{ featured.englishName }}</p>
          <p>{{ featured.description }}</p>
          <p class="studio__signature">{{ featured.signature }}</p>
          <ul class="studio__tags">
            <li v-for="tag in featured.tags" :key="tag" class="badge">{{ tag }}</li>
          </ul>
          <div class="studio__buttons">
            <button type="button" class="btn btn--primary" @click="seeInWorkbench(featured)">到工作台看效果</button>
            <button type="button" class="btn" :disabled="isPreviewing(featured) || (isApplied(featured) && !prefs.previewing)" @click="preview(featured)">
              試看這套
            </button>
          </div>
        </div>
      </div>
    </HudPanel>

    <!-- 圖庫 -->
    <section class="studio__gallery" aria-labelledby="gallery-title">
      <div class="studio__gallery-head">
        <h2 id="gallery-title" class="studio__h2">全部主題</h2>
        <div class="segmented" role="group" aria-label="分類篩選">
          <button
            v-for="c in categories"
            :key="c.value"
            type="button"
            :aria-pressed="category === c.value"
            @click="category = c.value"
          >
            {{ c.label }} <span class="num">{{ c.count }}</span>
          </button>
        </div>
        <label class="field studio__search">
          <span class="sr-only">搜尋主題</span>
          <input type="search" :value="query" :maxlength="QUERY_MAX" placeholder="搜尋名稱、風格或標籤" @input="onQuery" />
        </label>
        <span class="studio__count" aria-live="polite">顯示 <span class="num">{{ shown.length }}</span>／<span class="num">{{ THEMES.length }}</span> 套</span>
        <button type="button" class="btn btn--ghost btn--sm" :disabled="!hasFilters" @click="clearFilters">清除篩選</button>
      </div>

      <EmptyState v-if="shown.length === 0" title="沒有符合條件的主題" text="換個關鍵字，或清除分類篩選。">
        <button type="button" class="btn" @click="clearFilters">清除篩選</button>
      </EmptyState>

      <ul v-else class="studio__grid">
        <li v-for="t in shown" :key="t.id" :data-theme-card="t.id">
          <HudPanel as="article" :heading-level="3" :title="t.name" :code="t.id.toUpperCase()" :tone="isPreviewing(t) ? 'warn' : isApplied(t) ? 'accent' : 'default'">
            <ThemeThumb :theme="t" />
            <p class="studio__badges">
              <span class="badge">{{ CATEGORY_LABELS[t.category] }}</span>
              <span class="badge">{{ PANEL_STYLE_LABELS[t.panelStyle] }}</span>
              <span v-if="isApplied(t)" class="badge badge--accent">目前套用</span>
              <span v-if="isPreviewing(t)" class="badge badge--warn">試看中</span>
            </p>
            <ul class="studio__swatches" aria-label="色票">
              <li v-for="(hex, i) in t.palette" :key="i" :style="{ background: hex }" :title="hex">
                <span class="sr-only">{{ hex }}</span>
              </li>
            </ul>
            <p class="studio__english num">{{ t.englishName }}</p>
            <p class="studio__desc">{{ t.description }}</p>
            <p class="studio__signature">{{ t.signature }}</p>
            <ul class="studio__tags">
              <li v-for="tag in t.tags" :key="tag" class="badge">{{ tag }}</li>
            </ul>
            <div class="studio__buttons">
              <button
                type="button"
                class="btn"
                data-action="preview"
                :disabled="isPreviewing(t) || (isApplied(t) && !prefs.previewing)"
                @click="preview(t)"
              >
                試看這套
              </button>
              <button
                type="button"
                class="btn btn--primary"
                data-action="apply"
                :disabled="isApplied(t) && !prefs.previewing"
                @click="applyOrReturn(t)"
              >
                {{ applyLabel(t) }}
              </button>
            </div>
          </HudPanel>
        </li>
      </ul>
    </section>

    <!-- 元件樣本 -->
    <section class="studio__samples" aria-labelledby="samples-title">
      <h2 id="samples-title" class="studio__h2">儀表元件樣本 <span class="studio__note">（示範資料，不會寫入工作區）</span></h2>
      <div class="studio__sample-grid">
        <HudPanel title="單據生命週期" code="LFC">
          <ul class="studio__tracks">
            <li v-for="(s, i) in SAMPLE_ROWS" :key="i">
              <p class="studio__track-label">{{ LIFECYCLE_KINDS[s.kind] }} · {{ s.note }}</p>
              <LifecycleTrack :kind="s.kind" :row="s.row" />
            </li>
          </ul>
        </HudPanel>
        <HudPanel title="指標量表" code="GAU">
          <div class="studio__gauges">
            <Gauge label="庫存可用率" :value="82" caption="41／50 件" />
            <Gauge label="訂單付款率" :value="56" caption="9／16 筆" />
            <Gauge label="服務收款率" :value="3" :max="10" caption="3／10 筆" />
            <Gauge label="本週出勤達成率" :value="0" :max="0" caption="尚無班表" />
          </div>
        </HudPanel>
        <HudPanel title="步驟與分段進度" code="PRG">
          <div class="studio__progress">
            <StepProgress label="建置精靈" :steps="BUILD_STEPS" :current="2" />
            <StepProgress label="備份還原" :steps="['上傳', '驗證', '還原']" :current="1" :failed-at="1" />
            <ProgressBar label="上手引導完成度" :value="5" :max="8" />
            <ProgressBar label="備份上傳" :value="100" tone="ok" />
            <ProgressBar label="驗證備份內容" indeterminate />
          </div>
        </HudPanel>
        <HudPanel title="訊號燈" code="SIG">
          <div class="studio__signals">
            <StatusSignal tone="ok" label="已付清" />
            <StatusSignal tone="info" label="進行中" pulse />
            <StatusSignal tone="warn" label="待補件" />
            <StatusSignal tone="danger" label="庫存不足" />
            <StatusSignal tone="idle" label="未啟用" />
          </div>
        </HudPanel>
      </div>
    </section>

    <footer class="studio__foot">
      <p>主題、配色與密度彼此獨立，偏好只保存在這個瀏覽器。</p>
      <button v-if="prefs.previewing" type="button" class="btn btn--ghost" @click="prefs.cancelPreview()">取消這次試看</button>
    </footer>
  </div>
</template>

<style scoped>
.studio {
  display: grid;
  gap: calc(var(--gap) * 2);
  max-width: 1280px;
}
.studio__head {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: var(--gap) calc(var(--gap) * 2);
}
.studio__eyebrow {
  margin: 0;
  font-size: 0.72rem;
  letter-spacing: 0.24em;
  color: var(--accent);
}
.studio__title {
  margin: 4px 0;
  font-size: clamp(1.6rem, 3vw, 2.2rem);
  text-shadow: 0 0 18px var(--glow);
}
.studio__lead {
  margin: 0;
  max-width: 60ch;
  color: var(--ink-dim);
}
.studio__current {
  display: grid;
  gap: 8px;
  align-content: start;
  justify-items: start;
}
.studio__prefs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.studio__volatile {
  margin: 0;
  font-size: 0.8rem;
  color: var(--warn);
}
.studio__featured-body {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr);
  gap: calc(var(--gap) * 1.5);
  align-items: center;
}
.studio__featured-copy p {
  margin: 0 0 8px;
}
.studio__english {
  font-size: 0.72rem;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--ink-faint);
  margin: 0;
}
.studio__signature {
  color: var(--accent);
  font-size: 0.85rem;
}
.studio__tags,
.studio__swatches {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.studio__swatches li {
  width: 22px;
  height: 14px;
  border: 1px solid var(--line-strong);
  clip-path: polygon(4px 0, 100% 0, 100% 100%, 0 100%, 0 4px);
}
.studio__buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: var(--gap);
}
.studio__h2 {
  margin: 0;
  font-size: 1.2rem;
}
.studio__note {
  font-family: var(--font-body);
  font-size: 0.8rem;
  font-weight: 400;
  color: var(--ink-faint);
}
.studio__gallery,
.studio__samples {
  display: grid;
  gap: var(--gap);
}
.studio__gallery-head {
  display: flex;
  flex-wrap: wrap;
  gap: var(--gap);
  align-items: center;
}
.studio__search {
  flex: 1 1 200px;
  max-width: 320px;
}
.studio__count {
  color: var(--ink-dim);
  font-size: 0.85rem;
}
.studio__grid {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: calc(var(--gap) * 1.25);
}
.studio__grid > li > :deep(.hud) {
  height: 100%;
}
.studio__badges {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 10px 0 8px;
}
.studio__desc {
  margin: 6px 0;
  font-size: 0.9rem;
  color: var(--ink-dim);
}
.studio__sample-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: calc(var(--gap) * 1.25);
}
.studio__tracks {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 12px;
}
.studio__track-label {
  margin: 0 0 4px;
  font-size: 0.8rem;
  color: var(--ink-dim);
}
.studio__gauges {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--gap);
}
.studio__progress {
  display: grid;
  gap: calc(var(--gap) * 1.4);
}
.studio__signals {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
}
.studio__foot {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  gap: var(--gap);
  padding-top: var(--gap);
  border-top: 1px dashed var(--line);
  color: var(--ink-faint);
  font-size: 0.85rem;
}
.studio__foot p {
  margin: 0;
}
@media (max-width: 759.98px) {
  .studio__featured-body {
    grid-template-columns: 1fr;
  }
  .studio__grid,
  .studio__sample-grid {
    grid-template-columns: minmax(0, 1fr);
  }
  .studio__search {
    max-width: none;
  }
}
</style>
