<script setup lang="ts">
import { computed } from "vue";
import { formatSim } from "../../lib/format";
import type { Row } from "../../lib/records";
import LifecycleTrack from "../../ui/LifecycleTrack.vue";
import {
  actionPath,
  attendanceVoidForm,
  confirmForm,
  correctionForm,
  equipmentEditForm,
  noticeEditForm,
  requestEditForm,
  requestReturnForm,
  staffEditForm,
  unitEditForm,
  type AdminCommand,
  type AdminFormSpec,
} from "./adminForms";
import {
  WEEKDAY_LABELS,
  addDays,
  changesOf,
  equipmentName,
  hhmm,
  isDimStatus,
  isPast,
  monthDay,
  mondayOf,
  netMinutes,
  officeStatus,
  recordLabel,
  requestTypeLabel,
  rowStatus,
  staffAlias,
  startMs,
  taipeiDate,
  taipeiDateTime,
  unitName,
  weekdayIndex,
  type AdminTab,
  type DeskData,
} from "./adminModel";
import RecordHistory from "./RecordHistory.vue";

/**
 * 目前分頁的紀錄卡（A§5「Cards and screens」）。資料列來自 `/administration/rows`
 * （已依分頁篩選與排序）；名稱、更正紀錄等關聯資料取自工作區快照。
 * 卡片上的動作一律以表單或確認對話框呈現，emit `open(spec)` 交給工作台處理。
 */
const props = defineProps<{
  tab: AdminTab;
  rows: Row[];
  desk: DeskData;
  week: string;
  now: number;
  focusId: string;
  disabled: boolean;
}>();
const emit = defineEmits<{ open: [spec: AdminFormSpec] }>();

function s(row: Row, key: string): string {
  const v = row[key];
  return typeof v === "string" ? v : "";
}

function open(spec: AdminFormSpec): void {
  if (!props.disabled) emit("open", spec);
}

function command(tab: AdminTab, collection: string, row: Row, action: string, extra: Partial<AdminCommand> = {}): AdminCommand {
  return {
    method: "POST",
    path: actionPath(collection, row.id, action),
    body: {},
    tab,
    label: recordLabel(props.desk, tab, row),
    focusId: row.id,
    week: typeof row.start_at === "string" ? mondayOf(taipeiDate(row.start_at)) : undefined,
    ...extra,
  };
}

function confirm(title: string, note: string, cmd: AdminCommand, danger = false): void {
  open(confirmForm({ title, note, command: cmd, danger }));
}

function badgeClass(status: string): string {
  return isDimStatus(status) ? "badge badge--warn" : "badge";
}

function updated(row: Row): string {
  return `更新 ${taipeiDateTime(row.updated_at)}`;
}

// ── 班表 7 天 ─────────────────────────────────────────────
const today = computed(() => taipeiDate(props.now));
const days = computed(() =>
  Array.from({ length: 7 }, (_, i) => {
    const date = addDays(props.week, i);
    return { date, label: WEEKDAY_LABELS[i], rows: props.rows.filter((r) => taipeiDate(r.start_at) === date) };
  }),
);

function overnight(row: Row): string {
  const end = taipeiDate(row.end_at);
  return end && end !== taipeiDate(row.start_at) ? `至 ${monthDay(end)}（跨夜）` : "";
}

function shiftFinishReason(row: Row): string {
  return isPast(row.end_at, props.now) ? "" : `班次在 ${taipeiDateTime(row.end_at)} 結束後才能記錄結束。`;
}

// ── 手動出勤：依日期分組（伺服器已依開始時間由新到舊排序）─────
const attendanceGroups = computed(() => {
  const groups: { date: string; rows: Row[] }[] = [];
  for (const row of props.rows) {
    const date = taipeiDate(row.start_at);
    const last = groups[groups.length - 1];
    if (last && last.date === date) last.rows.push(row);
    else groups.push({ date, rows: [row] });
  }
  return groups;
});

// ── 組織、設備 ───────────────────────────────────────────
function staffCount(unitId: string): number {
  return props.desk.staff.filter((m) => m.unit_id === unitId).length;
}

function parentText(row: Row): string {
  return typeof row.parent_id === "string" ? `所屬門市：${unitName(props.desk, row.parent_id)}` : "獨立組織";
}

function equipmentBooking(row: Row): string {
  const mine = props.desk.reservations.filter((r) => r.equipment_id === row.id && r.status === "reserved");
  const current = mine.find((r) => startMs(r) <= props.now && !isPast(r.end_at, props.now));
  if (current) return `目前預約：${staffAlias(props.desk, current.staff_id)}，至 ${taipeiDateTime(current.end_at)}`;
  const future = mine.filter((r) => startMs(r) > props.now).length;
  return `目前沒有進行中的預約 · ${future} 筆未來預約`;
}

// ── 申請 ─────────────────────────────────────────────────
function transitions(row: Row): { at: string; status: string; note: string }[] {
  const list = Array.isArray(row.transitions) ? (row.transitions as Record<string, unknown>[]) : [];
  return list.map((t) => ({
    at: taipeiDateTime(t.at),
    status: officeStatus(typeof t.status === "string" ? t.status : ""),
    note: typeof t.note === "string" ? t.note : "",
  }));
}

function requestRange(row: Row): string {
  return `${taipeiDateTime(row.start_at)} → ${taipeiDateTime(row.end_at)}`;
}

// ── 公告 ─────────────────────────────────────────────────
function noticeDue(row: Row): { text: string; past: boolean } | null {
  if (typeof row.due_at !== "string") return null;
  const past = isPast(row.due_at, props.now);
  return { text: `${past ? "已截止" : "截止"} ${taipeiDateTime(row.due_at)}`, past };
}
</script>

<template>
  <div class="arec" :data-tab="tab">
    <!-- 週班表：7 天格 -->
    <template v-if="tab === 'shifts'">
      <p class="arec__hint">依各段開始日歸週，跨夜班次歸在開始那一天；本表只練習排班流程，不作薪資依據。</p>
      <ol class="arec__week" data-testid="shift-grid">
        <li v-for="d in days" :key="d.date" class="arec__day" :class="{ 'is-today': d.date === today }">
          <header class="arec__day-head">
            <span>{{ d.label }}</span>
            <span class="num">{{ monthDay(d.date) }}</span>
            <span class="arec__day-count num">{{ d.rows.length }} 班</span>
          </header>
          <p v-if="d.rows.length === 0" class="arec__day-empty">—</p>
          <article
            v-for="row in d.rows"
            :key="row.id"
            class="acard acard--compact"
            :class="{ 'is-target': focusId === row.id }"
            :data-record-id="row.id"
            tabindex="-1"
          >
            <p class="acard__time num">
              {{ hhmm(row.start_at) }}–{{ hhmm(row.end_at) }}
              <span v-if="overnight(row)" class="acard__overnight">{{ overnight(row) }}</span>
            </p>
            <p class="acard__title">{{ staffAlias(desk, row.staff_id) }}</p>
            <p class="acard__meta">{{ unitName(desk, row.unit_id) }} · 淨 {{ netMinutes(row) }} 分 · 休息 {{ row.break_minutes }} 分</p>
            <p v-if="s(row, 'note')" class="acard__text">{{ s(row, "note") }}</p>
            <p class="acard__foot">
              <span :class="badgeClass(rowStatus(tab, row))">{{ officeStatus(rowStatus(tab, row)) }}</span>
              <span class="acard__updated num">{{ updated(row) }}</span>
            </p>
            <RecordHistory :changes="changesOf(desk, row.id)" />
            <div v-if="row.status === 'scheduled'" class="acard__actions">
              <button type="button" class="btn btn--sm" :disabled="disabled" @click="open(correctionForm('shift', row, recordLabel(desk, 'shifts', row)))">編輯班次時段</button>
              <button
                type="button"
                class="btn btn--sm"
                :disabled="disabled || Boolean(shiftFinishReason(row))"
                :title="shiftFinishReason(row) || undefined"
                @click="confirm('結束班次', '把班次標記為已結束；不會自動建立手動出勤。', command('shifts', 'shifts', row, 'complete'))"
              >
                結束班次
              </button>
              <button
                type="button"
                class="btn btn--sm btn--ghost"
                :disabled="disabled"
                @click="confirm('取消班次', '取消後釋放這個時段，紀錄仍會保留。', command('shifts', 'shifts', row, 'cancel'), true)"
              >
                取消班次
              </button>
              <span v-if="shiftFinishReason(row)" class="acard__reason">{{ shiftFinishReason(row) }}</span>
            </div>
          </article>
        </li>
      </ol>
    </template>

    <!-- 手動出勤：依日期分組 -->
    <template v-else-if="tab === 'attendance'">
      <section v-for="g in attendanceGroups" :key="g.date" class="arec__group">
        <h3 class="arec__group-title num">{{ g.date }}（{{ WEEKDAY_LABELS[weekdayIndex(g.date)] }}）</h3>
        <ul class="arec__list">
          <li
            v-for="row in g.rows"
            :key="row.id"
            class="acard"
            :class="{ 'is-target': focusId === row.id, 'is-voided': row.voided === true }"
            :data-record-id="row.id"
            tabindex="-1"
          >
            <p class="acard__time num">
              {{ hhmm(row.start_at) }}–{{ hhmm(row.end_at) }}
              <span v-if="overnight(row)" class="acard__overnight">{{ overnight(row) }}</span>
            </p>
            <p class="acard__title">{{ staffAlias(desk, row.staff_id) }}</p>
            <p class="acard__meta">{{ unitName(desk, row.unit_id) }} · 淨 {{ netMinutes(row) }} 分 · 休息 {{ row.break_minutes }} 分</p>
            <p v-if="s(row, 'note')" class="acard__text">{{ s(row, "note") }}</p>
            <p v-if="row.voided === true" class="acard__warn">已作廢，統計不計入</p>
            <p class="acard__foot">
              <span :class="badgeClass(rowStatus(tab, row))">{{ officeStatus(rowStatus(tab, row)) }}</span>
              <span class="acard__updated num">{{ updated(row) }}</span>
            </p>
            <RecordHistory :changes="changesOf(desk, row.id)" />
            <div v-if="row.voided !== true" class="acard__actions">
              <button type="button" class="btn btn--sm" :disabled="disabled" @click="open(correctionForm('attendance', row, recordLabel(desk, 'attendance', row)))">更正手動出勤</button>
              <button type="button" class="btn btn--sm btn--ghost" :disabled="disabled" @click="open(attendanceVoidForm(row, recordLabel(desk, 'attendance', row)))">作廢手動出勤</button>
            </div>
          </li>
        </ul>
      </section>
    </template>

    <!-- 其他分頁：卡片清單 -->
    <ul v-else class="arec__list arec__list--grid">
      <li
        v-for="row in rows"
        :key="row.id"
        class="acard"
        :class="{ 'is-target': focusId === row.id }"
        :data-record-id="row.id"
        tabindex="-1"
      >
        <template v-if="tab === 'units'">
          <p class="acard__eyebrow">{{ row.kind === "branch" ? "門市" : "部門" }}</p>
          <p class="acard__title">{{ s(row, "name") }}</p>
          <p class="acard__meta">{{ parentText(row) }} · 假員工 <span class="num">{{ staffCount(row.id) }}</span> 位</p>
          <p class="acard__foot">
            <span :class="badgeClass(rowStatus(tab, row))">{{ officeStatus(rowStatus(tab, row)) }}</span>
            <span class="acard__updated num">{{ updated(row) }}</span>
          </p>
          <div class="acard__actions">
            <button type="button" class="btn btn--sm" :disabled="disabled" @click="open(unitEditForm(row))">編輯組織</button>
          </div>
        </template>

        <template v-else-if="tab === 'staff'">
          <p class="acard__eyebrow num">{{ s(row, "code") }} · {{ unitName(desk, row.unit_id) }}</p>
          <p class="acard__title">{{ s(row, "alias") }}</p>
          <p class="acard__meta">{{ s(row, "role_label") || "未填職務稱呼" }}</p>
          <p class="acard__foot">
            <span :class="badgeClass(rowStatus(tab, row))">{{ officeStatus(rowStatus(tab, row)) }}</span>
            <span class="acard__updated num">{{ updated(row) }}</span>
          </p>
          <div class="acard__actions">
            <button type="button" class="btn btn--sm" :disabled="disabled" @click="open(staffEditForm(row))">編輯假員工</button>
          </div>
        </template>

        <template v-else-if="tab === 'requests'">
          <p class="acard__eyebrow">
            {{ requestTypeLabel(row.type) }} · {{ unitName(desk, row.unit_id) }} · {{ typeof row.staff_id === "string" ? staffAlias(desk, row.staff_id) : "未指定" }}
          </p>
          <p class="acard__title">{{ s(row, "title") }}</p>
          <LifecycleTrack kind="request" :row="row" />
          <p v-if="s(row, 'description')" class="acard__text">{{ s(row, "description") }}</p>
          <p v-if="row.type === 'leave'" class="acard__meta num">{{ requestRange(row) }}</p>
          <p v-else-if="typeof row.amount_minor === 'number' && row.amount_minor > 0" class="acard__meta num">{{ formatSim(row.amount_minor) }}</p>
          <p v-if="s(row, 'processing_note')" class="acard__warn">最新退回原因：{{ s(row, "processing_note") }}</p>
          <p v-if="row.status === 'prepared_unreviewed'" class="acard__notice">已整理，尚未覆核；不代表准假、採購或付款。</p>
          <p class="acard__foot">
            <span :class="badgeClass(rowStatus(tab, row))">{{ officeStatus(rowStatus(tab, row)) }}</span>
            <span class="acard__updated num">{{ updated(row) }}</span>
          </p>
          <details class="acard__details">
            <summary>狀態與退回紀錄</summary>
            <ol class="acard__transitions">
              <li v-for="(t, i) in transitions(row)" :key="i">
                <span class="num">{{ t.at }}</span> {{ t.status }}<template v-if="t.note">：{{ t.note }}</template>
              </li>
            </ol>
          </details>
          <div class="acard__actions">
            <template v-if="row.status === 'draft' || row.status === 'returned'">
              <button type="button" class="btn btn--sm" :disabled="disabled" @click="open(requestEditForm(row))">編輯申請</button>
              <button
                type="button"
                class="btn btn--sm btn--primary"
                :disabled="disabled"
                @click="confirm('送出申請', '送出後狀態改為「待整理」，等待整理或退回補件。', command('requests', 'requests', row, 'submit'))"
              >
                送出申請
              </button>
            </template>
            <template v-if="row.status === 'submitted'">
              <button type="button" class="btn btn--sm" :disabled="disabled" @click="open(requestReturnForm(row))">退回補件</button>
              <button
                type="button"
                class="btn btn--sm btn--primary"
                :disabled="disabled"
                @click="confirm('整理完成（未覆核）', '只代表資料已整理完成，不是核准；不會准假、採購或付款，之後也無法再修改。', command('requests', 'requests', row, 'prepare'))"
              >
                整理完成（未覆核）
              </button>
            </template>
            <button
              v-if="row.status === 'draft' || row.status === 'submitted' || row.status === 'returned'"
              type="button"
              class="btn btn--sm btn--ghost"
              :disabled="disabled"
              @click="confirm('撤回申請', '撤回後申請結束，無法再編輯或送出；紀錄會保留。', command('requests', 'requests', row, 'withdraw'), true)"
            >
              撤回申請
            </button>
          </div>
        </template>

        <template v-else-if="tab === 'equipment'">
          <p class="acard__eyebrow num">{{ s(row, "code") }} · {{ unitName(desk, row.unit_id) }}</p>
          <p class="acard__title">{{ s(row, "name") }}</p>
          <p class="acard__meta">{{ equipmentBooking(row) }}</p>
          <p class="acard__foot">
            <span :class="badgeClass(rowStatus(tab, row))">{{ officeStatus(rowStatus(tab, row)) }}</span>
            <span class="acard__updated num">{{ updated(row) }}</span>
          </p>
          <div class="acard__actions">
            <button type="button" class="btn btn--sm" :disabled="disabled" @click="open(equipmentEditForm(row))">編輯設備</button>
          </div>
        </template>

        <template v-else-if="tab === 'reservations'">
          <p class="acard__eyebrow">{{ staffAlias(desk, row.staff_id) }}</p>
          <p class="acard__title">{{ equipmentName(desk, row.equipment_id) }}</p>
          <p class="acard__meta num">{{ taipeiDateTime(row.start_at) }} → {{ taipeiDateTime(row.end_at) }}</p>
          <p v-if="s(row, 'purpose')" class="acard__text">{{ s(row, "purpose") }}</p>
          <p class="acard__foot">
            <span :class="badgeClass(rowStatus(tab, row))">{{ officeStatus(rowStatus(tab, row)) }}</span>
            <span class="acard__updated num">{{ updated(row) }}</span>
          </p>
          <RecordHistory :changes="changesOf(desk, row.id)" />
          <div v-if="row.status === 'reserved'" class="acard__actions">
            <button type="button" class="btn btn--sm" :disabled="disabled" @click="open(correctionForm('reservation', row, recordLabel(desk, 'reservations', row)))">更改預約</button>
            <button
              type="button"
              class="btn btn--sm"
              :disabled="disabled"
              @click="confirm('記錄歸還', '把這筆借用標記為已歸還。', command('reservations', 'reservations', row, 'return', { week: undefined }))"
            >
              記錄歸還
            </button>
            <button
              type="button"
              class="btn btn--sm btn--ghost"
              :disabled="disabled"
              @click="confirm('取消預約', '取消後釋放設備時段，紀錄仍會保留。', command('reservations', 'reservations', row, 'cancel', { week: undefined }), true)"
            >
              取消預約
            </button>
          </div>
        </template>

        <template v-else-if="tab === 'notices'">
          <p class="acard__eyebrow">
            <template v-if="row.pinned === true && row.archived !== true">置頂 · </template>{{ typeof row.unit_id === "string" ? unitName(desk, row.unit_id) : "全體" }}<template v-if="row.archived === true"> · 已封存</template>
            <span v-if="noticeDue(row)" class="badge" :class="{ 'badge--warn': noticeDue(row)!.past }">{{ noticeDue(row)!.text }}</span>
          </p>
          <p class="acard__title">{{ s(row, "title") }}</p>
          <p class="acard__text">{{ s(row, "body") || "未填公告內容" }}</p>
          <p class="acard__foot">
            <span :class="badgeClass(rowStatus(tab, row))">{{ officeStatus(rowStatus(tab, row)) }}</span>
            <span class="acard__updated num">{{ updated(row) }}</span>
          </p>
          <RecordHistory :changes="changesOf(desk, row.id)" />
          <div class="acard__actions">
            <template v-if="row.archived !== true">
              <button type="button" class="btn btn--sm" :disabled="disabled" @click="open(noticeEditForm(desk, row))">編輯公告</button>
              <button
                type="button"
                class="btn btn--sm btn--ghost"
                :disabled="disabled"
                @click="confirm('封存公告', '封存後不再顯示於發布中列表，可從封存列表還原；資料會保留。', command('notices', 'notices', row, 'archive', { status: 'all' }))"
              >
                封存公告
              </button>
            </template>
            <button
              v-else
              type="button"
              class="btn btn--sm"
              :disabled="disabled"
              @click="confirm('還原公告', '還原後重新顯示於發布中列表。', command('notices', 'notices', row, 'restore'))"
            >
              還原公告
            </button>
          </div>
        </template>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.arec {
  display: grid;
  gap: var(--gap);
}
.arec__hint {
  margin: 0;
  font-size: 0.8rem;
  color: var(--ink-dim);
}
.arec__week {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 6px;
}
.arec__day {
  min-width: 0;
  display: grid;
  align-content: start;
  gap: 6px;
  padding: 6px;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--bg-deep);
}
.arec__day.is-today {
  border-color: var(--accent-2);
  box-shadow: inset 0 2px 0 var(--accent-2);
}
.arec__day-head {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 6px;
  align-items: baseline;
  font-size: 0.8rem;
}
.arec__day-count {
  margin-left: auto;
  color: var(--ink-faint);
  font-size: 0.72rem;
}
.arec__day-empty {
  margin: 0;
  color: var(--ink-faint);
  text-align: center;
}
@media (max-width: 1100px) {
  .arec__week {
    grid-template-columns: 1fr;
  }
}
.arec__group {
  display: grid;
  gap: 6px;
}
.arec__group-title {
  margin: 0;
  font-size: 0.85rem;
  color: var(--ink-dim);
  letter-spacing: 0.06em;
}
.arec__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: var(--gap);
}
.arec__list--grid {
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 300px), 1fr));
}
.acard {
  position: relative;
  min-width: 0;
  display: grid;
  gap: 4px;
  padding: var(--pad);
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  transition: border-color var(--motion-fast), box-shadow var(--motion-fast);
}
.acard--compact {
  padding: 8px;
  font-size: 0.85rem;
}
.acard:focus-visible,
.acard.is-target {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 1px var(--accent), 0 0 18px var(--glow);
}
.acard p {
  margin: 0;
  overflow-wrap: anywhere;
}
.acard__eyebrow {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  font-size: 0.75rem;
  letter-spacing: 0.06em;
  color: var(--ink-dim);
}
.acard__title {
  font-weight: 600;
}
.acard__time {
  color: var(--accent);
}
.acard__overnight {
  margin-left: 4px;
  font-size: 0.75rem;
  color: var(--accent-2);
}
.acard__meta,
.acard__text {
  font-size: 0.85rem;
  color: var(--ink-dim);
}
.acard__warn {
  font-size: 0.85rem;
  color: var(--warn);
}
.acard__notice {
  padding: 4px 8px;
  font-size: 0.8rem;
  border-left: 2px solid var(--accent-2);
  background: color-mix(in srgb, var(--accent-2) 8%, transparent);
}
.acard__foot {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  justify-content: space-between;
}
.acard__updated {
  font-size: 0.72rem;
  color: var(--ink-faint);
}
.acard__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 4px;
}
.acard__reason {
  font-size: 0.75rem;
  color: var(--ink-faint);
}
.acard__details summary {
  cursor: pointer;
  color: var(--ink-dim);
  font-size: 0.8rem;
}
.acard__transitions {
  margin: 4px 0 0;
  padding-left: 18px;
  font-size: 0.8rem;
  color: var(--ink-dim);
}
.is-voided .acard__time,
.is-voided .acard__title,
.is-voided .acard__meta {
  text-decoration: line-through;
  opacity: 0.7;
}
</style>
