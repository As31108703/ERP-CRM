/**
 * 行政表單（A§5「Create forms」「Client-side checks」）：欄位定義、預設值與前端預檢。
 * 每張表單的 `build` 把欄位值轉成 API 請求，預檢不通過時回傳錯誤訊息字串，不送出。
 *
 * 前端預檢只擋明顯錯誤（必填、整數範圍、時段長度、休息分鐘、更正沒有變更、週一日期），
 * 其餘規則（重疊、停用組織、狀態轉換）仍以伺服器為準。
 */
import type { MutateMethod } from "../../api/pending";
import { parseSim, simInput } from "../../lib/format";
import type { Row } from "../../lib/records";
import {
  ADMIN_API,
  REQUEST_TYPES,
  activeStaff,
  activeUnits,
  bookableEquipment,
  durationMinutes,
  isMonday,
  isValidDate,
  isoToTaipeiInput,
  mondayOf,
  addDays,
  recordLabel,
  staffOf,
  taipeiDate,
  taipeiInputToIso,
  unitName,
  type AdminTab,
  type DeskData,
} from "./adminModel";

export type { DeskData } from "./adminModel";

export type AdminValues = Record<string, string | boolean>;

export interface AdminOption {
  value: string;
  label: string;
}

export interface AdminField {
  name: string;
  label: string;
  type: "text" | "textarea" | "number" | "select" | "datetime" | "date" | "checkbox" | "money";
  required?: boolean;
  maxlength?: number;
  min?: number;
  max?: number;
  hint?: string;
  /** 下拉選單的空白選項文字；未設定時為「請選擇」。 */
  emptyLabel?: string;
  options?: (values: AdminValues) => AdminOption[];
  /** 依其他欄位決定是否顯示（例如請假才顯示起訖時間）。隱藏的欄位不做必填檢查。 */
  show?: (values: AdminValues) => boolean;
}

/** 送出的命令與成功後的定位方式（A§5「After a successful save」）。 */
export interface AdminCommand {
  method: MutateMethod;
  path: string;
  body: Record<string, unknown>;
  /** 成功後切到的分頁。 */
  tab: AdminTab;
  /** 成功訊息「已儲存「label」。」 */
  label: string;
  /** 成功後跳到的週（週一）。 */
  week?: string;
  /** 成功後該分頁的狀態篩選（預設重設為分頁預設值）。 */
  status?: string;
  /** 定位的紀錄；未設定時用回應的 `result`（新紀錄 id）。 */
  focusId?: string;
}

export interface AdminFormSpec {
  title: string;
  code: string;
  submitLabel: string;
  /** 表單上方的說明（確認類對話框用）。 */
  note?: string;
  danger?: boolean;
  fields: AdminField[];
  initial: AdminValues;
  /** 欄位改變後的連動（例如切換組織清除假員工）。直接修改 values。 */
  onChange?: (name: string, values: AdminValues) => void;
  build: (values: AdminValues) => AdminCommand | string;
}

const MINUTES_48H = 48 * 60;
const MINUTES_31D = 31 * 24 * 60;
export const BREAK_MAX = 2879;

const enc = encodeURIComponent;

// ── 讀值與預檢 ───────────────────────────────────────────

function text(values: AdminValues, name: string): string {
  const v = values[name];
  return typeof v === "string" ? v.trim() : "";
}

function flag(values: AdminValues, name: string): boolean {
  return values[name] === true || values[name] === "true";
}

function visible(field: AdminField, values: AdminValues): boolean {
  return field.show ? field.show(values) : true;
}

/** 必填檢查（只看目前顯示的欄位）。 */
export function missingField(fields: AdminField[], values: AdminValues): string | null {
  for (const f of fields) {
    if (!f.required || !visible(f, values) || f.type === "checkbox") continue;
    if (text(values, f.name) === "") return `請填寫「${f.label}」。`;
  }
  return null;
}

function lengthError(fields: AdminField[], values: AdminValues): string | null {
  for (const f of fields) {
    if (!f.maxlength || !visible(f, values)) continue;
    if (text(values, f.name).length > f.maxlength) return `「${f.label}」最多 ${f.maxlength} 字。`;
  }
  return null;
}

function precheck(fields: AdminField[], values: AdminValues): string | null {
  return missingField(fields, values) ?? lengthError(fields, values);
}

function readInt(values: AdminValues, name: string, label: string, min: number, max: number): number | string {
  const raw = text(values, name);
  const n = raw === "" ? 0 : Number(raw);
  if (!Number.isSafeInteger(n) || n < min || n > max) return `「${label}」請輸入 ${min} 到 ${max} 的整數。`;
  return n;
}

interface Span {
  start: string;
  end: string;
  minutes: number;
}

/** 起訖時間：可解析、結束晚於開始、長度不超過上限。 */
function readInterval(values: AdminValues, maxMinutes: number): Span | string {
  const start = taipeiInputToIso(text(values, "start_at"));
  if (!start) return "請輸入有效的開始時間（台北時間）。";
  const end = taipeiInputToIso(text(values, "end_at"));
  if (!end) return "請輸入有效的結束時間（台北時間）。";
  const minutes = durationMinutes(start, end);
  if (minutes <= 0) return "結束時間必須晚於開始時間。";
  if (maxMinutes === MINUTES_48H && minutes > maxMinutes) return "時段不可超過 48 小時。";
  if (minutes > maxMinutes) return "時段不可超過 31 天。";
  return { start, end, minutes };
}

function readBreak(values: AdminValues, minutes: number): number | string {
  const brk = readInt(values, "break_minutes", "休息分鐘", 0, BREAK_MAX);
  if (typeof brk === "string") return brk;
  if (brk >= minutes) return "休息分鐘必須小於時段長度。";
  return brk;
}

function weekDate(values: AdminValues, name: string, label: string): string | { error: string } {
  const date = text(values, name);
  if (!isValidDate(date) || !isMonday(date)) return { error: `「${label}」請選擇星期一（台北時間）。` };
  return date;
}

function nullable(values: AdminValues, name: string): string | null {
  const v = text(values, name);
  return v === "" ? null : v;
}

// ── 選項 ─────────────────────────────────────────────────

function unitOptions(rows: Row[]): AdminOption[] {
  return rows.map((u) => ({
    value: u.id,
    label: `${String(u.name ?? "")}${u.kind === "branch" ? "（門市）" : "（部門）"}${u.active === true ? "" : "（停用）"}`,
  }));
}

function staffOptions(desk: DeskData, rows: Row[]): AdminOption[] {
  return rows.map((s) => ({ value: s.id, label: `${String(s.alias ?? "")} · ${unitName(desk, s.unit_id)}` }));
}

const UNIT_KINDS: AdminOption[] = [
  { value: "branch", label: "門市" },
  { value: "department", label: "部門" },
];

const ACTIVE_OPTIONS: AdminOption[] = [
  { value: "true", label: "使用中" },
  { value: "false", label: "停用" },
];

const STAFF_STATUS: AdminOption[] = [
  { value: "active", label: "使用中" },
  { value: "inactive", label: "停用" },
];

const EQUIPMENT_STATES: AdminOption[] = [
  { value: "available", label: "可借用" },
  { value: "maintenance", label: "維修中" },
  { value: "retired", label: "已停用" },
];

export const DEMO_PRESETS: AdminOption[] = [
  { value: "store", label: "門市（合成示範門市）" },
  { value: "office", label: "辦公室（合成示範行政組）" },
  { value: "factory", label: "工廠（合成示範廠務組）" },
];

const TIME_HINT = "以台北時間（UTC+08:00）輸入，精確到分鐘。";

// ── 啟用與示範 ───────────────────────────────────────────

export function enableForm(): AdminFormSpec {
  return {
    title: "啟用行政模擬",
    code: "OFFICE-BOOT",
    submitLabel: "啟用行政模擬",
    note: "啟用後可練習組織、假員工、週班表、手動出勤、申請、設備借用與公告。所有資料都是合成示範，不影響錢包、帳本與其他業務資料。",
    fields: [],
    initial: {},
    build: () => ({ method: "POST", path: `${ADMIN_API}/enable`, body: {}, tab: "units", label: "行政模擬", focusId: "" }),
  };
}

export function demoForm(week: string): AdminFormSpec {
  const fields: AdminField[] = [
    { name: "preset", label: "示範情境", type: "select", required: true, options: () => DEMO_PRESETS },
    { name: "week_start", label: "示範週（星期一）", type: "date", required: true, hint: "班表、出勤與借用會排在這一週。" },
  ];
  return {
    title: "建立合成示範",
    code: "OFFICE-DEMO",
    submitLabel: "建立合成示範",
    note: "只能在行政資料完全空白時建立；會產生一個組織、兩位假員工、五個班次、兩筆手動出勤、一張請購草稿、一台設備、一筆借用與兩則公告。",
    fields,
    initial: { preset: "store", week_start: week },
    build: (v) => {
      const err = precheck(fields, v);
      if (err) return err;
      const week_start = weekDate(v, "week_start", "示範週");
      if (typeof week_start !== "string") return week_start.error;
      return {
        method: "POST",
        path: `${ADMIN_API}/demo`,
        body: { preset: text(v, "preset"), week_start },
        tab: "shifts",
        label: "合成示範",
        week: week_start,
        focusId: "",
      };
    },
  };
}

export function copyWeekForm(week: string): AdminFormSpec {
  const fields: AdminField[] = [
    { name: "from_date", label: "來源週（星期一）", type: "date", required: true },
    { name: "to_date", label: "目標週（星期一）", type: "date", required: true },
  ];
  return {
    title: "複製本週班表",
    code: "SHIFT-CLONE",
    submitLabel: "複製班表",
    note: "複製來源週所有未取消的班次（含已結束），保留假員工、組織、休息與備註，全部以「已排班」建立；任何一筆時段衝突就整批不寫入。",
    fields,
    initial: { from_date: week, to_date: addDays(week, 7) },
    build: (v) => {
      const err = precheck(fields, v);
      if (err) return err;
      const from = weekDate(v, "from_date", "來源週");
      if (typeof from !== "string") return from.error;
      const to = weekDate(v, "to_date", "目標週");
      if (typeof to !== "string") return to.error;
      if (from === to) return "來源週與目標週不可相同。";
      return {
        method: "POST",
        path: `${ADMIN_API}/shifts/copy-week`,
        body: { from_date: from, to_date: to },
        tab: "shifts",
        label: `${to} 週班表`,
        week: to,
      };
    },
  };
}

// ── 組織 ─────────────────────────────────────────────────

export function unitCreateForm(desk: DeskData): AdminFormSpec {
  const fields: AdminField[] = [
    { name: "name", label: "組織名稱", type: "text", required: true, maxlength: 80 },
    { name: "kind", label: "類型", type: "select", required: true, options: () => UNIT_KINDS },
    {
      name: "parent_id",
      label: "所屬門市",
      type: "select",
      emptyLabel: "不指定（獨立組織）",
      options: () => unitOptions(activeUnits(desk).filter((u) => u.kind === "branch")),
      hint: "只能選使用中的門市。",
    },
  ];
  return {
    title: "新增組織",
    code: "UNIT-NEW",
    submitLabel: "新增組織",
    fields,
    initial: { name: "", kind: "branch", parent_id: "" },
    build: (v) => {
      const err = precheck(fields, v);
      if (err) return err;
      const name = text(v, "name");
      return {
        method: "POST",
        path: `${ADMIN_API}/units`,
        body: { name, kind: text(v, "kind"), parent_id: nullable(v, "parent_id") },
        tab: "units",
        label: name,
      };
    },
  };
}

export function unitEditForm(row: Row): AdminFormSpec {
  const fields: AdminField[] = [
    { name: "name", label: "組織名稱", type: "text", required: true, maxlength: 80 },
    {
      name: "active",
      label: "狀態",
      type: "select",
      required: true,
      options: () => ACTIVE_OPTIONS,
      hint: "仍有使用中的下層組織、假員工、已排班次、未停用設備或待整理申請時無法停用。",
    },
  ];
  return {
    title: "編輯組織",
    code: "UNIT-EDIT",
    submitLabel: "儲存組織",
    fields,
    initial: { name: String(row.name ?? ""), active: row.active === true ? "true" : "false" },
    build: (v) => {
      const err = precheck(fields, v);
      if (err) return err;
      const name = text(v, "name");
      return {
        method: "PATCH",
        path: `${ADMIN_API}/units/${enc(row.id)}`,
        body: { name, active: text(v, "active") === "true" },
        tab: "units",
        label: name,
        focusId: row.id,
      };
    },
  };
}

// ── 假員工 ───────────────────────────────────────────────

export function staffCreateForm(desk: DeskData): AdminFormSpec {
  const fields: AdminField[] = [
    { name: "code", label: "假員工代號", type: "text", required: true, maxlength: 32, hint: "建立後不可修改，不分大小寫不可重複。" },
    { name: "alias", label: "暱稱", type: "text", required: true, maxlength: 80 },
    { name: "unit_id", label: "所屬組織", type: "select", required: true, options: () => unitOptions(activeUnits(desk)) },
    { name: "role_label", label: "職務稱呼", type: "text", maxlength: 80 },
  ];
  return {
    title: "加入假員工",
    code: "STAFF-NEW",
    submitLabel: "加入假員工",
    note: "假員工只用於流程練習，請勿輸入真實姓名或個人資料。",
    fields,
    initial: { code: "", alias: "", unit_id: activeUnits(desk)[0]?.id ?? "", role_label: "" },
    build: (v) => {
      const err = precheck(fields, v);
      if (err) return err;
      const alias = text(v, "alias");
      return {
        method: "POST",
        path: `${ADMIN_API}/staff`,
        body: { code: text(v, "code"), alias, unit_id: text(v, "unit_id"), role_label: text(v, "role_label") },
        tab: "staff",
        label: alias,
      };
    },
  };
}

export function staffEditForm(row: Row): AdminFormSpec {
  const fields: AdminField[] = [
    { name: "alias", label: "暱稱", type: "text", required: true, maxlength: 80 },
    { name: "role_label", label: "職務稱呼", type: "text", maxlength: 80 },
    {
      name: "status",
      label: "狀態",
      type: "select",
      required: true,
      options: () => STAFF_STATUS,
      hint: "仍有已排班次、進行中的借用或待整理申請時無法停用。",
    },
  ];
  return {
    title: "編輯假員工",
    code: "STAFF-EDIT",
    submitLabel: "儲存假員工",
    fields,
    initial: { alias: String(row.alias ?? ""), role_label: String(row.role_label ?? ""), status: String(row.status ?? "active") },
    build: (v) => {
      const err = precheck(fields, v);
      if (err) return err;
      const alias = text(v, "alias");
      return {
        method: "PATCH",
        path: `${ADMIN_API}/staff/${enc(row.id)}`,
        body: { alias, role_label: text(v, "role_label"), status: text(v, "status") },
        tab: "staff",
        label: alias,
        focusId: row.id,
      };
    },
  };
}

// ── 班次與手動出勤 ───────────────────────────────────────

function segmentFields(): AdminField[] {
  return [
    { name: "start_at", label: "開始時間", type: "datetime", required: true, hint: TIME_HINT },
    { name: "end_at", label: "結束時間", type: "datetime", required: true, hint: "跨夜時段歸在開始那一天；最長 48 小時。" },
    { name: "break_minutes", label: "休息分鐘", type: "number", min: 0, max: BREAK_MAX },
    { name: "note", label: "備註", type: "textarea", maxlength: 1000 },
  ];
}

/** 新增班次（tab = shifts）或手動出勤（tab = attendance）。unit_id 由所選假員工推得。 */
export function shiftCreateForm(desk: DeskData, tab: "shifts" | "attendance", week: string): AdminFormSpec {
  const isShift = tab === "shifts";
  const staff = activeStaff(desk);
  const fields: AdminField[] = [
    { name: "staff_id", label: "假員工", type: "select", required: true, options: () => staffOptions(desk, staff) },
    ...segmentFields(),
  ];
  const day = week || "";
  return {
    title: isShift ? "新增班次" : "新增手動出勤",
    code: isShift ? "SHIFT-NEW" : "ATTEND-NEW",
    submitLabel: isShift ? "新增班次" : "新增手動出勤",
    note: isShift ? undefined : "手動輸入的實際工時，不是真實打卡紀錄，也不作薪資依據。",
    fields,
    initial: {
      staff_id: staff[0]?.id ?? "",
      start_at: day ? `${day}T09:00` : "",
      end_at: day ? `${day}T17:00` : "",
      break_minutes: "0",
      note: "",
    },
    build: (v) => {
      const err = precheck(fields, v);
      if (err) return err;
      const member = staffOf(desk, text(v, "staff_id"));
      if (!member) return "請選擇假員工。";
      const span = readInterval(v, MINUTES_48H);
      if (typeof span === "string") return span;
      const brk = readBreak(v, span.minutes);
      if (typeof brk === "string") return brk;
      return {
        method: "POST",
        path: `${ADMIN_API}/${isShift ? "shifts" : "attendance"}`,
        body: {
          staff_id: member.id,
          unit_id: member.unit_id,
          start_at: span.start,
          end_at: span.end,
          break_minutes: brk,
          note: text(v, "note"),
        },
        tab,
        label: `${String(member.alias ?? "")} ${taipeiDate(span.start)} ${isShift ? "班次" : "出勤"}`,
        week: mondayOf(taipeiDate(span.start)),
      };
    },
  };
}

export type CorrectionKind = "shift" | "attendance" | "reservation";

const CORRECTION_META: Record<CorrectionKind, { tab: AdminTab; path: string; title: string; code: string; max: number }> = {
  shift: { tab: "shifts", path: "shifts", title: "編輯班次時段", code: "SHIFT-FIX", max: MINUTES_48H },
  attendance: { tab: "attendance", path: "attendance", title: "更正手動出勤", code: "ATTEND-FIX", max: MINUTES_48H },
  reservation: { tab: "reservations", path: "reservations", title: "更改預約", code: "RESV-FIX", max: MINUTES_31D },
};

/**
 * 附原因的更正（班次、手動出勤、借用）。預設值為原紀錄；只送出有變更的欄位，
 * 沒有任何欄位變更時在前端擋下（伺服器也會拒絕無變更的更正）。
 */
export function correctionForm(kind: CorrectionKind, row: Row, label?: string): AdminFormSpec {
  const meta = CORRECTION_META[kind];
  const isReservation = kind === "reservation";
  const fields: AdminField[] = isReservation
    ? [
        { name: "start_at", label: "開始時間", type: "datetime", required: true, hint: TIME_HINT },
        { name: "end_at", label: "結束時間", type: "datetime", required: true, hint: "最長 31 天。" },
        { name: "purpose", label: "借用用途", type: "textarea", maxlength: 1000 },
      ]
    : segmentFields();
  fields.push({
    name: "reason",
    label: "更正原因",
    type: "textarea",
    required: true,
    maxlength: 1000,
    hint: "原因與更正前後內容會保留在「更正與保留紀錄」。",
  });

  const initial: AdminValues = {
    start_at: isoToTaipeiInput(row.start_at),
    end_at: isoToTaipeiInput(row.end_at),
    reason: "",
  };
  if (isReservation) initial.purpose = String(row.purpose ?? "");
  else {
    initial.break_minutes = String(typeof row.break_minutes === "number" ? row.break_minutes : 0);
    initial.note = String(row.note ?? "");
  }

  return {
    title: meta.title,
    code: meta.code,
    submitLabel: "儲存更正",
    fields,
    initial,
    build: (v) => {
      const reason = text(v, "reason");
      if (!reason) return "請填寫「更正原因」。";
      const err = precheck(fields, v);
      if (err) return err;
      const span = readInterval(v, meta.max);
      if (typeof span === "string") return span;
      const body: Record<string, unknown> = { reason };
      if (text(v, "start_at") !== initial.start_at) body.start_at = span.start;
      if (text(v, "end_at") !== initial.end_at) body.end_at = span.end;
      if (isReservation) {
        const purpose = text(v, "purpose");
        if (purpose !== String(row.purpose ?? "")) body.purpose = purpose;
      } else {
        const brk = readBreak(v, span.minutes);
        if (typeof brk === "string") return brk;
        if (brk !== row.break_minutes) body.break_minutes = brk;
        const note = text(v, "note");
        if (note !== String(row.note ?? "")) body.note = note;
      }
      if (Object.keys(body).length === 1) return "沒有任何欄位變更，請修改後再送出更正。";
      return {
        method: "PATCH",
        path: `${ADMIN_API}/${meta.path}/${enc(row.id)}`,
        body,
        tab: meta.tab,
        label: label ?? meta.title,
        week: mondayOf(taipeiDate(span.start)),
        focusId: row.id,
      };
    },
  };
}

export function attendanceVoidForm(row: Row, label = "作廢手動出勤"): AdminFormSpec {
  const fields: AdminField[] = [
    { name: "reason", label: "作廢原因", type: "textarea", required: true, maxlength: 1000 },
  ];
  return {
    title: "作廢手動出勤",
    code: "ATTEND-VOID",
    submitLabel: "作廢手動出勤",
    danger: true,
    note: "作廢後紀錄仍保留，但不再計入工時，也不再擋住重疊的新紀錄。",
    fields,
    initial: { reason: "" },
    build: (v) => {
      const err = precheck(fields, v);
      if (err) return err;
      return {
        method: "POST",
        path: `${ADMIN_API}/attendance/${enc(row.id)}/void`,
        body: { reason: text(v, "reason") },
        tab: "attendance",
        label,
        status: "all",
        week: mondayOf(taipeiDate(row.start_at)),
        focusId: row.id,
      };
    },
  };
}

// ── 申請 ─────────────────────────────────────────────────

const isLeave = (v: AdminValues) => v.type === "leave";

/** 金額欄位：一般申請可為 0，請購與費用至少 0.01 SIM，上限 10,000,000 SIM。 */
function readAmount(values: AdminValues, type: string): number | string {
  const minor = parseSim(text(values, "amount_sim"));
  if (minor === null) return "「SIM 金額」請以 SIM 輸入，最多兩位小數，上限 10,000,000 SIM。";
  if (type !== "general" && minor < 1) return "「SIM 金額」至少 0.01 SIM。";
  return minor;
}

export function requestCreateForm(desk: DeskData): AdminFormSpec {
  const units = activeUnits(desk);
  const fields: AdminField[] = [
    { name: "type", label: "申請類型", type: "select", required: true, options: () => [...REQUEST_TYPES] },
    { name: "unit_id", label: "組織", type: "select", required: true, options: () => unitOptions(units) },
    {
      name: "staff_id",
      label: "假員工",
      type: "select",
      emptyLabel: "不指定",
      options: (v) => staffOptions(desk, activeStaff(desk).filter((s) => s.unit_id === v.unit_id)),
      hint: "只列出所選組織的使用中假員工；請假必填。",
    },
    { name: "title", label: "標題", type: "text", required: true, maxlength: 100 },
    { name: "description", label: "內容", type: "textarea", maxlength: 1000 },
    { name: "start_at", label: "開始時間", type: "datetime", show: isLeave, hint: TIME_HINT },
    { name: "end_at", label: "結束時間", type: "datetime", show: isLeave, hint: "請假最長 31 天。" },
    {
      name: "amount_sim",
      label: "SIM 金額",
      type: "money",
      show: (v) => !isLeave(v),
      hint: "請購與費用需大於 0；一般申請可填 0。只是模擬數字，不會移動任何測試幣。",
    },
  ];
  return {
    title: "新增申請",
    code: "REQ-NEW",
    submitLabel: "建立申請草稿",
    note: "申請只練習行政資料整理；「整理完成」不代表准假、採購或付款。",
    fields,
    initial: {
      type: "general",
      unit_id: units[0]?.id ?? "",
      staff_id: "",
      title: "",
      description: "",
      start_at: "",
      end_at: "",
      amount_sim: "0",
    },
    onChange: (name, v) => {
      if (name === "unit_id") v.staff_id = "";
      if (name === "type") {
        v.amount_sim = "";
        v.start_at = "";
        v.end_at = "";
      }
    },
    build: (v) => {
      const err = precheck(fields, v);
      if (err) return err;
      const type = text(v, "type");
      const unit_id = text(v, "unit_id");
      const staff_id = nullable(v, "staff_id");
      if (staff_id && staffOf(desk, staff_id)?.unit_id !== unit_id) return "所選假員工不屬於這個組織。";
      const title = text(v, "title");
      const body: Record<string, unknown> = {
        type,
        unit_id,
        staff_id,
        title,
        description: text(v, "description"),
      };
      let week: string | undefined;
      if (type === "leave") {
        if (!staff_id) return "請假必須指定「假員工」。";
        if (!text(v, "start_at")) return "請假必須填寫「開始時間」。";
        if (!text(v, "end_at")) return "請假必須填寫「結束時間」。";
        const span = readInterval(v, MINUTES_31D);
        if (typeof span === "string") return span;
        body.start_at = span.start;
        body.end_at = span.end;
        // 請假一律不帶金額（A§1：leave 的 amount_minor 必須為 0）。
        body.amount_minor = 0;
        week = mondayOf(taipeiDate(span.start));
      } else {
        if (!text(v, "amount_sim")) return "請填寫「SIM 金額」。";
        const amount = readAmount(v, type);
        if (typeof amount === "string") return amount;
        body.amount_minor = amount;
      }
      return { method: "POST", path: `${ADMIN_API}/requests`, body, tab: "requests", label: title, week };
    },
  };
}

export function requestEditForm(row: Row): AdminFormSpec {
  const type = String(row.type ?? "general");
  const leave = type === "leave";
  const fields: AdminField[] = [
    { name: "title", label: "標題", type: "text", required: true, maxlength: 100 },
    { name: "description", label: "內容", type: "textarea", maxlength: 1000 },
  ];
  if (leave) {
    fields.push(
      { name: "start_at", label: "開始時間", type: "datetime", required: true, hint: TIME_HINT },
      { name: "end_at", label: "結束時間", type: "datetime", required: true, hint: "請假最長 31 天。" },
    );
  } else {
    fields.push({
      name: "amount_sim",
      label: "SIM 金額",
      type: "money",
      required: true,
      hint: type === "general" ? "一般申請可填 0。" : "至少 0.01 SIM。",
    });
  }
  return {
    title: "編輯申請",
    code: "REQ-EDIT",
    submitLabel: "儲存申請",
    note: row.status === "returned" ? "退回補件的申請儲存後會回到草稿，需要再送出一次。" : undefined,
    fields,
    initial: {
      title: String(row.title ?? ""),
      description: String(row.description ?? ""),
      start_at: isoToTaipeiInput(row.start_at),
      end_at: isoToTaipeiInput(row.end_at),
      amount_sim: simInput(typeof row.amount_minor === "number" ? row.amount_minor : 0),
    },
    build: (v) => {
      const err = precheck(fields, v);
      if (err) return err;
      const title = text(v, "title");
      const body: Record<string, unknown> = { title, description: text(v, "description") };
      if (leave) {
        const span = readInterval(v, MINUTES_31D);
        if (typeof span === "string") return span;
        body.start_at = span.start;
        body.end_at = span.end;
      } else {
        const amount = readAmount(v, type);
        if (typeof amount === "string") return amount;
        body.amount_minor = amount;
      }
      return {
        method: "PATCH",
        path: `${ADMIN_API}/requests/${enc(row.id)}`,
        body,
        tab: "requests",
        label: title,
        focusId: row.id,
      };
    },
  };
}

export function requestReturnForm(row: Row): AdminFormSpec {
  const fields: AdminField[] = [
    { name: "processing_note", label: "退回原因", type: "textarea", required: true, maxlength: 1000 },
  ];
  return {
    title: "退回補件",
    code: "REQ-RETURN",
    submitLabel: "退回補件",
    note: "退回原因會顯示在申請卡上，並保留在狀態紀錄中。",
    fields,
    initial: { processing_note: "" },
    build: (v) => {
      const err = precheck(fields, v);
      if (err) return err;
      return {
        method: "POST",
        path: `${ADMIN_API}/requests/${enc(row.id)}/return`,
        body: { processing_note: text(v, "processing_note") },
        tab: "requests",
        label: String(row.title ?? "申請"),
        focusId: row.id,
      };
    },
  };
}

// ── 設備與借用 ───────────────────────────────────────────

export function equipmentCreateForm(desk: DeskData): AdminFormSpec {
  const fields: AdminField[] = [
    { name: "code", label: "設備代號", type: "text", required: true, maxlength: 32, hint: "建立後不可修改，不分大小寫不可重複。" },
    { name: "name", label: "設備名稱", type: "text", required: true, maxlength: 80 },
    { name: "unit_id", label: "所屬組織", type: "select", required: true, options: () => unitOptions(activeUnits(desk)) },
  ];
  return {
    title: "新增設備",
    code: "EQUIP-NEW",
    submitLabel: "新增設備",
    fields,
    initial: { code: "", name: "", unit_id: activeUnits(desk)[0]?.id ?? "" },
    build: (v) => {
      const err = precheck(fields, v);
      if (err) return err;
      const name = text(v, "name");
      return {
        method: "POST",
        path: `${ADMIN_API}/equipment`,
        body: { code: text(v, "code"), name, unit_id: text(v, "unit_id") },
        tab: "equipment",
        label: name,
      };
    },
  };
}

export function equipmentEditForm(row: Row): AdminFormSpec {
  const fields: AdminField[] = [
    { name: "name", label: "設備名稱", type: "text", required: true, maxlength: 80 },
    {
      name: "state",
      label: "狀態",
      type: "select",
      required: true,
      options: () => EQUIPMENT_STATES,
      hint: "仍有已預約的借用時無法改為維修中或停用。",
    },
  ];
  return {
    title: "編輯設備",
    code: "EQUIP-EDIT",
    submitLabel: "儲存設備",
    fields,
    initial: { name: String(row.name ?? ""), state: String(row.state ?? "available") },
    build: (v) => {
      const err = precheck(fields, v);
      if (err) return err;
      const name = text(v, "name");
      return {
        method: "PATCH",
        path: `${ADMIN_API}/equipment/${enc(row.id)}`,
        body: { name, state: text(v, "state") },
        tab: "equipment",
        label: name,
        focusId: row.id,
      };
    },
  };
}

export function reservationCreateForm(desk: DeskData, week: string): AdminFormSpec {
  const equipment = bookableEquipment(desk);
  const staff = activeStaff(desk);
  const fields: AdminField[] = [
    {
      name: "equipment_id",
      label: "設備",
      type: "select",
      required: true,
      options: () => equipment.map((e) => ({ value: e.id, label: `${String(e.name ?? "")} · ${unitName(desk, e.unit_id)}` })),
    },
    { name: "staff_id", label: "借用人（假員工）", type: "select", required: true, options: () => staffOptions(desk, staff) },
    { name: "start_at", label: "開始時間", type: "datetime", required: true, hint: TIME_HINT },
    { name: "end_at", label: "結束時間", type: "datetime", required: true, hint: "最長 31 天；同一設備的預約不可重疊。" },
    { name: "purpose", label: "借用用途", type: "textarea", maxlength: 500 },
  ];
  return {
    title: "新增借用",
    code: "RESV-NEW",
    submitLabel: "建立預約",
    fields,
    initial: {
      equipment_id: equipment[0]?.id ?? "",
      staff_id: staff[0]?.id ?? "",
      start_at: week ? `${week}T13:00` : "",
      end_at: week ? `${week}T15:00` : "",
      purpose: "",
    },
    build: (v) => {
      const err = precheck(fields, v);
      if (err) return err;
      const span = readInterval(v, MINUTES_31D);
      if (typeof span === "string") return span;
      const equipmentId = text(v, "equipment_id");
      return {
        method: "POST",
        path: `${ADMIN_API}/reservations`,
        body: {
          equipment_id: equipmentId,
          staff_id: text(v, "staff_id"),
          start_at: span.start,
          end_at: span.end,
          purpose: text(v, "purpose"),
        },
        tab: "reservations",
        label: recordLabel(desk, "reservations", { equipment_id: equipmentId }),
      };
    },
  };
}

// ── 公告 ─────────────────────────────────────────────────

function noticeFields(unitChoices: () => AdminOption[]): AdminField[] {
  return [
    { name: "title", label: "公告標題", type: "text", required: true, maxlength: 100 },
    { name: "body", label: "公告內容", type: "textarea", maxlength: 2000 },
    { name: "unit_id", label: "公告對象", type: "select", emptyLabel: "全體", options: unitChoices },
    { name: "pinned", label: "置頂公告", type: "checkbox" },
    { name: "due_at", label: "截止時間（選填）", type: "datetime", hint: TIME_HINT },
  ];
}

function noticeBody(v: AdminValues): Record<string, unknown> | string {
  const dueText = text(v, "due_at");
  let due_at: string | null = null;
  if (dueText) {
    due_at = taipeiInputToIso(dueText);
    if (!due_at) return "請輸入有效的截止時間（台北時間）。";
  }
  return {
    title: text(v, "title"),
    body: text(v, "body"),
    unit_id: nullable(v, "unit_id"),
    pinned: flag(v, "pinned"),
    due_at,
  };
}

export function noticeCreateForm(desk: DeskData): AdminFormSpec {
  const fields = noticeFields(() => unitOptions(activeUnits(desk)));
  return {
    title: "新增公告",
    code: "NOTICE-NEW",
    submitLabel: "發布公告",
    fields,
    initial: { title: "", body: "", unit_id: "", pinned: false, due_at: "" },
    build: (v) => {
      const err = precheck(fields, v);
      if (err) return err;
      const body = noticeBody(v);
      if (typeof body === "string") return body;
      return { method: "POST", path: `${ADMIN_API}/notices`, body, tab: "notices", label: String(body.title) };
    },
  };
}

export function noticeEditForm(desk: DeskData, row: Row): AdminFormSpec {
  // 選項含目前所屬的停用組織，避免編輯其他欄位時被迫改公告對象。
  const fields = noticeFields(() =>
    unitOptions(desk.units.filter((u) => u.active === true || u.id === row.unit_id)),
  );
  return {
    title: "編輯公告",
    code: "NOTICE-EDIT",
    submitLabel: "儲存公告",
    fields,
    initial: {
      title: String(row.title ?? ""),
      body: String(row.body ?? ""),
      unit_id: typeof row.unit_id === "string" ? row.unit_id : "",
      pinned: row.pinned === true,
      due_at: isoToTaipeiInput(row.due_at),
    },
    build: (v) => {
      const err = precheck(fields, v);
      if (err) return err;
      const body = noticeBody(v);
      if (typeof body === "string") return body;
      return {
        method: "PATCH",
        path: `${ADMIN_API}/notices/${enc(row.id)}`,
        body,
        tab: "notices",
        label: String(body.title),
        focusId: row.id,
      };
    },
  };
}

// ── 確認類動作 ───────────────────────────────────────────

/** 不需要輸入的動作（結束班次、送出申請、封存公告…）：只顯示確認說明。 */
export function confirmForm(opts: {
  title: string;
  note: string;
  submitLabel?: string;
  danger?: boolean;
  command: AdminCommand;
}): AdminFormSpec {
  return {
    title: opts.title,
    code: "CONFIRM",
    submitLabel: opts.submitLabel ?? opts.title,
    note: opts.note,
    danger: opts.danger,
    fields: [],
    initial: {},
    build: () => opts.command,
  };
}

/** 卡片上的動作路徑（`/<collection>/<id>/<action>`）。 */
export function actionPath(collection: string, id: string, action: string): string {
  return `${ADMIN_API}/${collection}/${enc(id)}/${action}`;
}

