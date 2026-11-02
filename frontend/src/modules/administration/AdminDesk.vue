<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ApiError, get } from "../../api/client";
import type { MutationResult } from "../../api/types";
import { downloadFile, fetchText } from "../../lib/download";
import { prefersReducedMotion } from "../../lib/search";
import EmptyState from "../../ui/EmptyState.vue";
import HudPanel from "../../ui/HudPanel.vue";
import StepProgress from "../../ui/StepProgress.vue";
import PageHead from "../shared/PageHead.vue";
import { usePage } from "../shared/usePage";
import AdminForms from "./AdminForms.vue";
import {
  copyWeekForm,
  demoForm,
  enableForm,
  equipmentCreateForm,
  noticeCreateForm,
  requestCreateForm,
  reservationCreateForm,
  shiftCreateForm,
  staffCreateForm,
  unitCreateForm,
  type AdminCommand,
  type AdminFormSpec,
} from "./adminForms";
import {
  ADMIN_API,
  ADMIN_TABS,
  DEFAULT_TAB,
  QUERY_MAX,
  REQUEST_TYPES,
  STATUS_OPTIONS,
  WEEK_TABS,
  activeStaff,
  activeUnits,
  addDays,
  bookableEquipment,
  currentWeek,
  defaultStatus,
  deskIsEmpty,
  deskOf,
  mondayOf,
  printDataFromCsv,
  rowsOfTab,
  tabLabel,
  tabOfKind,
  taipeiDate,
  type AdminOverview,
  type AdminRows,
  type AdminTab,
  type DeskData,
  type DiffRow,
  type OverviewTile,
  type PrintData,
} from "./adminModel";
import AdminRecords from "./AdminRecords.vue";
import AdminTabs from "./AdminTabs.vue";
import AttendanceDiff from "./AttendanceDiff.vue";
import PrintSheet from "./PrintSheet.vue";

/**
 * 行政工作台（A§5）。資料列、篩選統計、待辦概覽與出勤差異由伺服器計算
 * （`/administration/rows`、`/overview`、`/attendance-diff`），CSV 與列印共用同一套篩選。
 * 名稱、更正紀錄等關聯資料取自工作區快照的 `administration`。
 */
const { store, ws, resetKey, enabled } = usePage();
const route = useRoute();
const router = useRouter();

const SEARCH_DEBOUNCE_MS = 250;
const NOW_REFRESH_MS = 30_000;
const idPrefix = `adm-${Math.random().toString(36).slice(2, 8)}`;

const active = computed(() => enabled("administration"));
const emptyDesk: DeskData = {
  units: [],
  staff: [],
  shifts: [],
  attendance: [],
  requests: [],
  equipment: [],
  reservations: [],
  notices: [],
  changes: [],
};
const desk = computed<DeskData>(() => deskOf(ws.value) ?? emptyDesk);
const version = computed(() => store.view?.version ?? 0);

// ── 介面狀態（換工作區世代時全部重設）──────────────────────
function initialStatus(): Record<AdminTab, string> {
  return Object.fromEntries(ADMIN_TABS.map((t) => [t.id, defaultStatus(t.id)])) as Record<AdminTab, string>;
}

const now = ref(Date.now());
const tab = ref<AdminTab>(DEFAULT_TAB);
const searchInput = ref("");
const q = ref("");
const unit = ref("");
const statusByTab = reactive<Record<AdminTab, string>>(initialStatus());
const requestType = ref("all");
const week = ref(currentWeek(now.value));
const focusId = ref("");
/** 目前的定位是否來自路由上的 target；按「清除定位」移除 target 時一併取消醒目標示。 */
let routeFocused = false;
const onboardingOpen = ref<boolean | null>(null);

const overview = ref<AdminOverview | null>(null);
const listing = ref<AdminRows | null>(null);
const diff = ref<DiffRow[]>([]);
const rowsError = ref("");
const overviewError = ref("");
/** 列表與概覽各自記錄錯誤，任一邊成功只清除自己的錯誤。 */
const loadError = computed(() => rowsError.value || overviewError.value);
const diffError = ref("");
const toolError = ref("");
const printData = ref<PrintData | null>(null);

const formSpec = ref<AdminFormSpec | null>(null);
const formError = ref("");

function resetState(): void {
  tab.value = DEFAULT_TAB;
  searchInput.value = "";
  q.value = "";
  unit.value = "";
  Object.assign(statusByTab, initialStatus());
  requestType.value = "all";
  week.value = currentWeek(Date.now());
  focusId.value = "";
  onboardingOpen.value = null;
  overview.value = null;
  listing.value = null;
  diff.value = [];
  toolError.value = "";
  formSpec.value = null;
  formError.value = "";
}

watch(resetKey, (next, prev) => {
  if (prev !== undefined && next !== prev) resetState();
});

let clock: ReturnType<typeof setInterval> | null = null;
let searchTimer: ReturnType<typeof setTimeout> | null = null;
onMounted(() => {
  clock = setInterval(() => (now.value = Date.now()), NOW_REFRESH_MS);
});
onBeforeUnmount(() => {
  if (clock) clearInterval(clock);
  if (searchTimer) clearTimeout(searchTimer);
});

const isWeekTab = computed(() => WEEK_TABS.includes(tab.value));
const status = computed({
  get: () => statusByTab[tab.value],
  set: (v: string) => {
    statusByTab[tab.value] = v;
  },
});

// ── 伺服器檢視 ───────────────────────────────────────────
function query(params: Record<string, string>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== "") sp.set(k, v);
  return sp.toString();
}

const rowsParams = computed(() => ({
  tab: tab.value,
  unit: unit.value,
  q: q.value,
  status: status.value,
  type: tab.value === "requests" ? requestType.value : "",
  week: week.value,
}));

function messageOf(err: unknown): string {
  return err instanceof ApiError ? err.message : "讀取行政資料失敗，請重新讀取。";
}

let rowsSeq = 0;
async function loadRows(): Promise<void> {
  if (!active.value) return;
  const seq = ++rowsSeq;
  try {
    const data = await get<AdminRows>(`${ADMIN_API}/rows?${query(rowsParams.value)}`);
    if (seq !== rowsSeq) return;
    listing.value = data;
    rowsError.value = "";
  } catch (err) {
    if (seq !== rowsSeq) return;
    rowsError.value = messageOf(err);
  }
}

let overviewSeq = 0;
async function loadOverview(): Promise<void> {
  if (!active.value) return;
  const seq = ++overviewSeq;
  try {
    const data = await get<AdminOverview>(`${ADMIN_API}/overview?${query({ week: week.value, unit: unit.value })}`);
    if (seq !== overviewSeq) return;
    overview.value = data;
    overviewError.value = "";
  } catch (err) {
    if (seq === overviewSeq) overviewError.value = messageOf(err);
  }
}

let diffSeq = 0;
async function loadDiff(): Promise<void> {
  if (!active.value || tab.value !== "attendance") return;
  const seq = ++diffSeq;
  try {
    const data = await get<DiffRow[]>(`${ADMIN_API}/attendance-diff?${query({ week: week.value, unit: unit.value })}`);
    if (seq !== diffSeq) return;
    diff.value = data;
    diffError.value = "";
  } catch (err) {
    if (seq === diffSeq) diffError.value = messageOf(err);
  }
}

watch([active, version, resetKey, rowsParams], () => void loadRows(), { immediate: true });
watch([active, version, resetKey, week, unit], () => void loadOverview(), { immediate: true });
watch([active, version, resetKey, week, unit, tab], () => void loadDiff(), { immediate: true });

const rows = computed(() => listing.value?.rows ?? []);

// ── 篩選 ─────────────────────────────────────────────────
/** 使用者自行改篩選時取消定位（含路由上的 target）。 */
function userFilter(): void {
  focusId.value = "";
  routeFocused = false;
  if (route.query.target !== undefined) {
    const next = { ...route.query };
    delete next.target;
    void router.replace({ query: next });
  }
}

function onSearch(event: Event): void {
  searchInput.value = (event.target as HTMLInputElement).value.slice(0, QUERY_MAX);
  userFilter();
  if (searchTimer) clearTimeout(searchTimer);
  searchTimer = setTimeout(() => (q.value = searchInput.value), SEARCH_DEBOUNCE_MS);
}

function setSearch(text: string): void {
  if (searchTimer) clearTimeout(searchTimer);
  searchInput.value = text;
  q.value = text;
}

function onUnit(event: Event): void {
  unit.value = (event.target as HTMLSelectElement).value;
  userFilter();
}

function onStatus(event: Event): void {
  status.value = (event.target as HTMLSelectElement).value;
  userFilter();
}

function onType(event: Event): void {
  requestType.value = (event.target as HTMLSelectElement).value;
  userFilter();
}

function selectTab(next: AdminTab): void {
  if (next === tab.value) return;
  tab.value = next;
  userFilter();
}

const hasFilters = computed(
  () => q.value !== "" || searchInput.value !== "" || unit.value !== "" || status.value !== defaultStatus(tab.value) || (tab.value === "requests" && requestType.value !== "all"),
);

function clearFilters(): void {
  setSearch("");
  unit.value = "";
  status.value = defaultStatus(tab.value);
  requestType.value = "all";
  userFilter();
}

function moveWeek(days: number): void {
  week.value = addDays(week.value, days);
  userFilter();
}

function thisWeek(): void {
  week.value = currentWeek(Date.now());
  userFilter();
}

const weekLabel = computed(() => `${week.value} 至 ${addDays(week.value, 6)}`);

// ── 定位（?target=<kind>:<id> 或儲存成功後）────────────────────
function focusRecord(target: { tab: AdminTab; id: string; week?: string; status?: string }): void {
  tab.value = target.tab;
  setSearch("");
  unit.value = "";
  statusByTab[target.tab] = target.status ?? defaultStatus(target.tab);
  if (target.tab === "requests") requestType.value = "all";
  if (target.week) week.value = target.week;
  focusId.value = target.id;
}

function applyRouteTarget(): void {
  const raw = route.query.target;
  if (typeof raw !== "string") {
    if (routeFocused) focusId.value = "";
    routeFocused = false;
    return;
  }
  if (!active.value) return;
  const at = raw.indexOf(":");
  if (at <= 0) return;
  const kind = raw.slice(0, at);
  const id = raw.slice(at + 1);
  const targetTab = tabOfKind(kind);
  if (!targetTab || !id) return;
  const row = rowsOfTab(desk.value, targetTab).find((r) => r.id === id);
  if (!row) return;
  // 定位時清除篩選並顯示全部狀態（作廢、封存的紀錄也看得到）。
  focusRecord({
    tab: targetTab,
    id,
    status: "all",
    week: typeof row.start_at === "string" ? mondayOf(taipeiDate(row.start_at)) : undefined,
  });
  routeFocused = true;
}

watch(() => [route.query.target, resetKey.value, active.value] as const, applyRouteTarget, { immediate: true });

const panel = ref<HTMLElement | null>(null);
watch(
  () => [focusId.value, listing.value] as const,
  async ([id]) => {
    if (!id) return;
    await nextTick();
    const el = Array.from(panel.value?.querySelectorAll<HTMLElement>("[data-record-id]") ?? []).find(
      (node) => node.dataset.recordId === id,
    );
    if (!el) return;
    el.focus({ preventScroll: true });
    el.scrollIntoView?.({ block: "center", behavior: prefersReducedMotion() ? "auto" : "smooth" });
  },
);

// ── 概覽磚與入門路線 ─────────────────────────────────────
function openTile(tile: OverviewTile): void {
  const t = tile.target;
  const next = ADMIN_TABS.find((x) => x.id === t.tab)?.id;
  if (!next) return;
  userFilter();
  tab.value = next;
  if (t.unit !== undefined) unit.value = t.unit ?? "";
  statusByTab[next] = t.status ?? defaultStatus(next);
  if (next === "requests") requestType.value = t.type ?? "all";
  setSearch(t.q ?? "");
}

const onboarding = computed(() => overview.value?.onboarding ?? null);
const onboardingCurrent = computed(() => {
  const steps = onboarding.value?.steps ?? [];
  const i = steps.findIndex((s) => !s.done);
  return i < 0 ? steps.length : i;
});
const onboardingExpanded = computed(() => onboardingOpen.value ?? onboarding.value?.open ?? false);

function onToggleOnboarding(event: Event): void {
  onboardingOpen.value = (event.target as HTMLDetailsElement).open;
}

// ── 新增按鈕的前置條件 ───────────────────────────────────
const NEED_UNIT = "先新增一個使用中的門市或部門。";
const NEED_STAFF = "先新增使用中組織與假員工。";
const NEED_RESERVATION = "需要使用中的假員工，以及使用中組織裡可借用的設備。";

const hasActiveUnit = computed(() => activeUnits(desk.value).length > 0);
const hasActiveStaff = computed(() => activeStaff(desk.value).length > 0);

const CREATE_LABELS: Record<AdminTab, string> = {
  units: "新增組織",
  staff: "加入假員工",
  shifts: "新增班次",
  attendance: "新增手動出勤",
  requests: "新增申請",
  equipment: "新增設備",
  reservations: "新增借用",
  notices: "新增公告",
};

function createReason(t: AdminTab): string {
  if (t === "staff" || t === "requests" || t === "equipment") return hasActiveUnit.value ? "" : NEED_UNIT;
  if (t === "shifts" || t === "attendance") return hasActiveStaff.value ? "" : NEED_STAFF;
  if (t === "reservations") {
    return hasActiveStaff.value && bookableEquipment(desk.value).length > 0 ? "" : NEED_RESERVATION;
  }
  return "";
}

function createSpec(t: AdminTab): AdminFormSpec {
  const d = desk.value;
  switch (t) {
    case "units":
      return unitCreateForm(d);
    case "staff":
      return staffCreateForm(d);
    case "shifts":
    case "attendance":
      return shiftCreateForm(d, t, week.value);
    case "requests":
      return requestCreateForm(d);
    case "equipment":
      return equipmentCreateForm(d);
    case "reservations":
      return reservationCreateForm(d, week.value);
    case "notices":
      return noticeCreateForm(d);
  }
}

function openCreate(t: AdminTab): void {
  if (createReason(t) || store.busy) return;
  selectTab(t);
  openForm(createSpec(t));
}

const ONBOARDING_TABS: Record<string, AdminTab> = { unit: "units", staff: "staff", shift: "shifts" };

const demoReason = computed(() => (deskIsEmpty(desk.value) ? "" : "行政資料完全空白時才能建立合成示範。"));
const copyReason = computed(() => {
  const start = week.value;
  const end = addDays(start, 7);
  const has = desk.value.shifts.some((s) => {
    const d = taipeiDate(s.start_at);
    return s.status !== "cancelled" && d >= start && d < end;
  });
  return has ? "" : "這週沒有未取消的班次可以複製。";
});

// ── 表單送出與儲存後定位 ─────────────────────────────────
function openForm(spec: AdminFormSpec): void {
  formError.value = "";
  formSpec.value = spec;
}

function closeForm(): void {
  if (store.busy) return;
  formSpec.value = null;
  formError.value = "";
}

async function submitForm(cmd: AdminCommand): Promise<void> {
  if (store.busy) return;
  formError.value = "";
  const res = await store.run<MutationResult>(cmd.method, cmd.path, cmd.body);
  if (res === null) {
    formError.value = store.error || "操作尚未完成，請稍後再試。";
    return;
  }
  formSpec.value = null;
  store.message = `已儲存「${cmd.label}」。`;
  const id = cmd.focusId ?? (typeof res.result === "string" ? res.result : "");
  if (route.query.target !== undefined) userFilter();
  focusRecord({ tab: cmd.tab, id, week: cmd.week, status: cmd.status });
}

// ── 匯出與列印 ───────────────────────────────────────────
const exportQuery = computed(() => query(rowsParams.value));
const canExport = computed(() => rows.value.length > 0 && !rowsError.value);

async function exportCsv(): Promise<void> {
  toolError.value = "";
  const name = `erpcrm-admin-${tab.value}-${taipeiDate(Date.now())}.csv`;
  const err = await downloadFile(`${ADMIN_API}/export.csv?${exportQuery.value}`, name);
  if (err) toolError.value = err;
}

async function printSheet(): Promise<void> {
  toolError.value = "";
  const res = await fetchText(`${ADMIN_API}/export.csv?${exportQuery.value}`);
  if ("error" in res) {
    toolError.value = res.error;
    return;
  }
  const data = printDataFromCsv(tab.value, res.text);
  if (!data) {
    toolError.value = "目前範圍沒有可列印的紀錄。";
    return;
  }
  printData.value = data;
  await nextTick();
  window.print();
}

const unitOptions = computed(() =>
  desk.value.units.map((u) => ({ value: u.id, label: `${String(u.name ?? "")}${u.active === true ? "" : "（停用）"}` })),
);
const counts = computed(() => Object.fromEntries(ADMIN_TABS.map((t) => [t.id, desk.value[t.id].length])) as Record<AdminTab, number>);
</script>

<template>
  <div class="adesk" data-testid="page-administration">
    <PageHead
      code="OFFICE · DESK · SIM-HR"
      title="行政工作台"
      lead="以合成資料練習組織、假員工、週班表、手動出勤、申請、設備借用與公告。所有時間以臺北時間（UTC+08:00）呈現，不作薪資、准假、採購或付款依據。"
    >
      <template v-if="active">
        <button
          type="button"
          class="btn"
          data-testid="admin-demo"
          :disabled="Boolean(demoReason) || store.busy"
          :title="demoReason || undefined"
          @click="openForm(demoForm(week))"
        >
          建立合成示範
        </button>
        <span v-if="demoReason" class="phead__reason">{{ demoReason }}</span>
      </template>
    </PageHead>

    <!-- 未啟用：啟用面板 -->
    <HudPanel v-if="!active" title="行政模擬尚未啟用" code="OFFICE-OFF" tone="accent" data-testid="admin-enable-panel">
      <p class="adesk__lead">
        啟用後會新增一個空白的行政工作台，可練習排班、出勤更正、申請退回與設備借用。不會改動錢包、帳本、商品或其他業務資料。
      </p>
      <button type="button" class="btn btn--primary" data-testid="admin-enable" :disabled="store.busy" @click="openForm(enableForm())">
        啟用行政模擬
      </button>
    </HudPanel>

    <template v-else>
      <!-- 入門路線 -->
      <details v-if="onboarding" class="adesk__onboard" :open="onboardingExpanded" data-testid="admin-onboarding" @toggle="onToggleOnboarding">
        <summary>
          <span class="adesk__onboard-title">行政入門路線</span>
          <span class="adesk__onboard-summary">{{ onboarding.summary }}</span>
        </summary>
        <StepProgress :steps="onboarding.steps.map((s) => s.label)" :current="onboardingCurrent" label="行政入門路線" />
        <ol class="adesk__onboard-steps">
          <li v-for="step in onboarding.steps" :key="step.id" :class="{ 'is-done': step.done }">
            <p class="adesk__onboard-label">{{ step.label }}</p>
            <p class="adesk__onboard-detail">{{ step.detail }}</p>
            <button
              type="button"
              class="btn btn--sm"
              :class="{ 'btn--primary': !step.done }"
              :disabled="store.busy || Boolean(createReason(ONBOARDING_TABS[step.id] ?? 'units'))"
              @click="openCreate(ONBOARDING_TABS[step.id] ?? 'units')"
            >
              {{ step.button }}
            </button>
            <span v-if="createReason(ONBOARDING_TABS[step.id] ?? 'units')" class="adesk__reason">{{ step.reason || createReason(ONBOARDING_TABS[step.id] ?? 'units') }}</span>
          </li>
        </ol>
      </details>

      <!-- 待辦概覽 -->
      <section v-if="overview" class="adesk__tiles" aria-label="行政待辦概覽" data-testid="admin-tiles">
        <button v-for="t in overview.tiles" :key="t.id" type="button" class="adesk__tile" :data-tile="t.id" @click="openTile(t)">
          <span class="adesk__tile-label">{{ t.label }}</span>
          <span class="adesk__tile-value num">{{ t.value ?? "—" }}<small v-if="t.unit && t.value !== null"> {{ t.unit }}</small></span>
          <span class="adesk__tile-sub">{{ t.sub }}</span>
        </button>
      </section>

      <HudPanel class="adesk__main" code="DESK-GRID">
        <AdminTabs :model-value="tab" :counts="counts" :id-prefix="idPrefix" @update:model-value="selectTab" />

        <div :id="`${idPrefix}-panel`" ref="panel" role="tabpanel" :aria-labelledby="`${idPrefix}-tab-${tab}`" class="adesk__panel">
          <!-- 工具列 -->
          <div class="adesk__tools" data-testid="admin-toolbar">
            <label class="field adesk__grow">
              <span class="field__label">搜尋</span>
              <input type="search" :value="searchInput" :maxlength="QUERY_MAX" placeholder="輸入關鍵字（不分大小寫）" data-testid="admin-search" @input="onSearch" />
            </label>
            <label class="field">
              <span class="field__label">組織</span>
              <select :value="unit" data-testid="admin-unit" @change="onUnit">
                <option value="">全部組織</option>
                <option v-for="o in unitOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
              </select>
            </label>
            <label v-if="tab === 'requests'" class="field">
              <span class="field__label">申請類型</span>
              <select :value="requestType" data-testid="admin-type" @change="onType">
                <option value="all">全部類型</option>
                <option v-for="o in REQUEST_TYPES" :key="o.value" :value="o.value">{{ o.label }}</option>
              </select>
            </label>
            <label class="field">
              <span class="field__label">狀態</span>
              <select :value="status" data-testid="admin-status" @change="onStatus">
                <option v-for="o in STATUS_OPTIONS[tab]" :key="o.value" :value="o.value">{{ o.label }}</option>
              </select>
            </label>
            <div class="adesk__create">
              <button
                type="button"
                class="btn btn--primary"
                data-testid="admin-create"
                :disabled="Boolean(createReason(tab)) || store.busy"
                @click="openCreate(tab)"
              >
                {{ CREATE_LABELS[tab] }}
              </button>
              <span v-if="createReason(tab)" class="adesk__reason" data-testid="admin-create-reason">{{ createReason(tab) }}</span>
            </div>
          </div>

          <!-- 週切換 -->
          <div v-if="isWeekTab" class="adesk__week" data-testid="admin-week">
            <button type="button" class="btn btn--ghost btn--sm" aria-label="上一週" @click="moveWeek(-7)">←</button>
            <button type="button" class="btn btn--ghost btn--sm" @click="thisWeek">本週</button>
            <button type="button" class="btn btn--ghost btn--sm" aria-label="下一週" @click="moveWeek(7)">→</button>
            <span class="adesk__week-label num" data-testid="admin-week-label">{{ weekLabel }}</span>
            <button
              v-if="tab === 'shifts'"
              type="button"
              class="btn btn--sm"
              data-testid="admin-copy-week"
              :disabled="Boolean(copyReason) || store.busy"
              :title="copyReason || undefined"
              @click="openForm(copyWeekForm(week))"
            >
              複製本週班表
            </button>
          </div>

          <div class="adesk__status">
            <p class="adesk__count" aria-live="polite" data-testid="admin-count">
              目前篩選 <span class="num">{{ rows.length }}</span> 筆 · {{ listing?.status_scope ?? "讀取中" }}
            </p>
            <div class="adesk__status-actions">
              <button type="button" class="btn btn--ghost btn--sm" :disabled="!hasFilters" @click="clearFilters">清除篩選</button>
              <button type="button" class="btn btn--sm" data-testid="admin-export" :disabled="!canExport" @click="exportCsv">匯出目前範圍 CSV</button>
              <button type="button" class="btn btn--sm" data-testid="admin-print" :disabled="!canExport" @click="printSheet">列印目前範圍</button>
            </div>
          </div>
          <p v-if="listing" class="adesk__summary" data-testid="admin-summary">{{ listing.summary }}</p>
          <p class="adesk__source num">
            資料來源：工作區版本 v{{ version }} · {{ listing?.period ?? "—" }} · Asia/Taipei（UTC+08:00）· {{ tabLabel(tab) }}
          </p>
          <p v-if="toolError" class="adesk__error" role="alert">{{ toolError }}</p>
          <p v-if="loadError" class="adesk__error" role="alert" data-testid="admin-load-error">
            {{ loadError }}
            <button type="button" class="btn btn--sm" @click="loadRows(); loadOverview()">重新讀取</button>
          </p>

          <AttendanceDiff v-if="tab === 'attendance'" :rows="diff" :period="weekLabel" :error="diffError" />

          <AdminRecords
            v-if="rows.length || tab === 'shifts'"
            :tab="tab"
            :rows="rows"
            :desk="desk"
            :week="week"
            :now="now"
            :focus-id="focusId"
            :disabled="store.busy"
            @open="openForm"
          />
          <EmptyState
            v-if="listing && rows.length === 0 && tab !== 'shifts'"
            :title="desk[tab].length ? '沒有符合條件的紀錄' : '尚無資料'"
            :text="desk[tab].length ? '目前的搜尋、組織或狀態篩選沒有符合的紀錄。' : `還沒有${tabLabel(tab)}資料。`"
          >
            <button v-if="hasFilters" type="button" class="btn" @click="clearFilters">清除篩選</button>
          </EmptyState>
        </div>
      </HudPanel>
    </template>

    <AdminForms :spec="formSpec" :error="formError" @submit="submitForm" @close="closeForm" />
    <PrintSheet :data="printData" />
  </div>
</template>

<style scoped>
.adesk {
  display: grid;
  gap: calc(var(--gap) * 1.25);
}
.adesk__lead {
  margin: 0 0 var(--gap);
  color: var(--ink-dim);
  max-width: 64ch;
}
.adesk__onboard {
  padding: var(--pad);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--surface);
}
.adesk__onboard summary {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
  align-items: baseline;
  cursor: pointer;
  margin-bottom: 8px;
}
.adesk__onboard-title {
  font-family: var(--font-display);
  letter-spacing: 0.04em;
}
.adesk__onboard-summary {
  font-size: 0.8rem;
  color: var(--ink-dim);
}
.adesk__onboard-steps {
  list-style: none;
  margin: var(--gap) 0 0;
  padding: 0;
  display: grid;
  gap: var(--gap);
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 220px), 1fr));
}
.adesk__onboard-steps li {
  display: grid;
  gap: 4px;
  align-content: start;
  justify-items: start;
  padding: 8px 10px;
  border-left: 2px solid var(--line-strong);
}
.adesk__onboard-steps li.is-done {
  border-left-color: var(--accent);
}
.adesk__onboard-label {
  margin: 0;
  font-weight: 600;
}
.adesk__onboard-detail {
  margin: 0;
  font-size: 0.8rem;
  color: var(--ink-dim);
}
.adesk__reason {
  font-size: 0.78rem;
  color: var(--ink-faint);
}
.adesk__tiles {
  display: grid;
  gap: var(--gap);
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 200px), 1fr));
}
.adesk__tile {
  display: grid;
  gap: 2px;
  justify-items: start;
  padding: 10px 12px;
  text-align: left;
  font: inherit;
  color: var(--ink);
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: border-color var(--motion-fast), box-shadow var(--motion-fast);
}
.adesk__tile:hover,
.adesk__tile:focus-visible {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 12px var(--glow);
}
.adesk__tile-label {
  font-size: 0.75rem;
  letter-spacing: 0.08em;
  color: var(--ink-dim);
}
.adesk__tile-value {
  font-size: 1.4rem;
  color: var(--accent);
}
.adesk__tile-value small {
  font-size: 0.75rem;
  color: var(--ink-dim);
}
.adesk__tile-sub {
  font-size: 0.78rem;
  color: var(--ink-faint);
  overflow-wrap: anywhere;
}
.adesk__panel {
  display: grid;
  gap: var(--gap);
  margin-top: var(--gap);
}
.adesk__tools {
  display: flex;
  flex-wrap: wrap;
  gap: var(--gap);
  align-items: flex-end;
}
.adesk__grow {
  flex: 1 1 220px;
}
.adesk__create {
  display: grid;
  gap: 4px;
  justify-items: start;
}
.adesk__week {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
.adesk__week-label {
  font-size: 0.85rem;
  color: var(--ink-dim);
}
.adesk__status {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  justify-content: space-between;
}
.adesk__status-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.adesk__count,
.adesk__summary,
.adesk__source {
  margin: 0;
  font-size: 0.85rem;
  color: var(--ink-dim);
}
.adesk__source {
  font-size: 0.72rem;
  color: var(--ink-faint);
}
.adesk__error {
  margin: 0;
  padding: 8px 10px;
  border-left: 3px solid var(--danger);
  background: color-mix(in srgb, var(--danger) 10%, transparent);
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
</style>
