/**
 * 行政工作台的共用模型（A§5、A§7）：分頁、狀態篩選、狀態文字、台北時間換算與週次計算。
 * 行政頁所有時間一律以台北時間（UTC+08:00）顯示與輸入，週一為一週第一天。
 */
import type { Rec, Row } from "../../lib/records";

export const ADMIN_API = "/api/v1/administration";

export const ADMIN_TABS = [
  { id: "units", label: "組織", kind: "unit" },
  { id: "staff", label: "假員工", kind: "staff" },
  { id: "shifts", label: "週班表", kind: "shift" },
  { id: "attendance", label: "手動出勤", kind: "attendance" },
  { id: "requests", label: "申請", kind: "request" },
  { id: "equipment", label: "設備", kind: "equipment" },
  { id: "reservations", label: "借用", kind: "reservation" },
  { id: "notices", label: "公告", kind: "notice" },
] as const;

export type AdminTab = (typeof ADMIN_TABS)[number]["id"];
export type AdminKind = (typeof ADMIN_TABS)[number]["kind"];

export const DEFAULT_TAB: AdminTab = "shifts";
export const WEEK_TABS: readonly AdminTab[] = ["shifts", "attendance"];
export const QUERY_MAX = 120;

export function isAdminTab(value: unknown): value is AdminTab {
  return ADMIN_TABS.some((t) => t.id === value);
}

export function tabLabel(tab: AdminTab): string {
  return ADMIN_TABS.find((t) => t.id === tab)?.label ?? tab;
}

export function kindOfTab(tab: AdminTab): AdminKind {
  return ADMIN_TABS.find((t) => t.id === tab)!.kind;
}

export function tabOfKind(kind: string): AdminTab | null {
  return ADMIN_TABS.find((t) => t.kind === kind)?.id ?? null;
}

/** 各分頁的狀態篩選選項（第一個是預設值，與後端 `/rows` 相同）。 */
export const STATUS_OPTIONS: Record<AdminTab, { value: string; label: string }[]> = {
  units: [
    { value: "all", label: "全部組織" },
    { value: "active", label: "使用中" },
    { value: "inactive", label: "停用" },
  ],
  staff: [
    { value: "all", label: "全部假員工" },
    { value: "active", label: "使用中" },
    { value: "inactive", label: "停用" },
  ],
  shifts: [
    { value: "all", label: "全部班次" },
    { value: "scheduled", label: "已排班" },
    { value: "completed", label: "已結束" },
    { value: "cancelled", label: "已取消" },
  ],
  attendance: [
    { value: "active", label: "有效紀錄" },
    { value: "voided", label: "已作廢" },
    { value: "all", label: "全部（含作廢）" },
  ],
  requests: [
    { value: "all", label: "全部狀態" },
    { value: "draft", label: "草稿" },
    { value: "submitted", label: "待整理" },
    { value: "returned", label: "退回補件" },
    { value: "withdrawn", label: "已撤回" },
    { value: "prepared_unreviewed", label: "整理完成（未覆核）" },
  ],
  equipment: [
    { value: "all", label: "全部設備" },
    { value: "available_now", label: "目前可用" },
    { value: "available", label: "可借用" },
    { value: "maintenance", label: "維修中" },
    { value: "retired", label: "已停用" },
  ],
  reservations: [
    { value: "all", label: "全部借用" },
    { value: "reserved", label: "已預約" },
    { value: "returned", label: "已歸還" },
    { value: "cancelled", label: "已取消" },
  ],
  notices: [
    { value: "active", label: "發布中" },
    { value: "archived", label: "已封存" },
    { value: "all", label: "發布中與封存" },
  ],
};

export function defaultStatus(tab: AdminTab): string {
  return STATUS_OPTIONS[tab][0].value;
}

export const REQUEST_TYPES = [
  { value: "leave", label: "請假" },
  { value: "purchase", label: "請購" },
  { value: "expense", label: "費用" },
  { value: "general", label: "一般申請" },
] as const;

export function requestTypeLabel(type: unknown): string {
  return REQUEST_TYPES.find((t) => t.value === type)?.label ?? "申請";
}

/** A§7 狀態文字；借用的 returned 顯示「已歸還」，申請的 returned 顯示「退回補件」。 */
const OFFICE_STATUS: Record<string, string> = {
  active: "使用中",
  inactive: "停用",
  scheduled: "已排班",
  completed: "已結束",
  cancelled: "已取消",
  draft: "草稿",
  submitted: "待整理",
  returned: "退回補件",
  withdrawn: "已撤回",
  prepared_unreviewed: "整理完成（未覆核）",
  available: "可借用",
  maintenance: "維修中",
  retired: "已停用",
  reserved: "已預約",
  reservation_returned: "已歸還",
  recorded: "有效紀錄",
  voided: "已作廢",
  archived: "已封存",
  published: "發布中",
};

export function officeStatus(key: string): string {
  return OFFICE_STATUS[key] ?? key;
}

/** 紀錄的狀態鍵（顯示用）。 */
export function rowStatus(tab: AdminTab, row: Rec): string {
  switch (tab) {
    case "units":
      return row.active === true ? "active" : "inactive";
    case "attendance":
      return row.voided === true ? "voided" : "recorded";
    case "equipment":
      return str(row.state);
    case "notices":
      return row.archived === true ? "archived" : "published";
    case "reservations":
      return row.status === "returned" ? "reservation_returned" : str(row.status);
    default:
      return str(row.status);
  }
}

/** 停用、取消、作廢、封存這類「已結束」的狀態，徽章改用警示色。 */
export function isDimStatus(status: string): boolean {
  return ["inactive", "cancelled", "withdrawn", "retired", "voided", "archived", "maintenance"].includes(status);
}

function str(v: unknown): string {
  return typeof v === "string" ? v : "";
}

// ── 台北時間 ─────────────────────────────────────────────

const TAIPEI_OFFSET_MS = 8 * 3600_000;
const DAY_MS = 86_400_000;
const INPUT_RE = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/;
const DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;

function toMs(value: unknown): number {
  if (typeof value === "number") return value;
  if (typeof value !== "string") return NaN;
  return Date.parse(value);
}

/** 台北牆上時間的 ISO 片段（`YYYY-MM-DDTHH:MM`）。 */
function taipeiParts(value: unknown): string {
  const ms = toMs(value);
  if (Number.isNaN(ms)) return "";
  return new Date(ms + TAIPEI_OFFSET_MS).toISOString().slice(0, 16);
}

/** ISO → `<input type="datetime-local">` 的台北時間值；無法解析時回傳空字串。 */
export function isoToTaipeiInput(value: unknown): string {
  return taipeiParts(value);
}

/**
 * 台北時間輸入 → 分鐘對齊、帶 `+08:00` 的 ISO。格式不符、日期溢位（例如 2 月 30 日）
 * 或來回換算不一致時回傳 null。
 */
export function taipeiInputToIso(value: string): string | null {
  const text = value.trim();
  const m = INPUT_RE.exec(text);
  if (!m) return null;
  const [y, mo, d, h, mi] = m.slice(1).map(Number);
  if (y < 1 || h > 23 || mi > 59) return null;
  const ms = Date.UTC(y, mo - 1, d, h, mi) - TAIPEI_OFFSET_MS;
  // 來回換算一致才接受（擋掉 2 月 30 日這類會被 Date 自動進位的日期）。
  return taipeiParts(ms) === text ? `${text}:00+08:00` : null;
}

/** 台北日期 `YYYY-MM-DD`。 */
export function taipeiDate(value: unknown): string {
  return taipeiParts(value).slice(0, 10);
}

function dateMs(date: string): number {
  const m = DATE_RE.exec(date);
  if (!m) return NaN;
  const ms = Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return new Date(ms).toISOString().slice(0, 10) === date ? ms : NaN;
}

export function isValidDate(date: string): boolean {
  return !Number.isNaN(dateMs(date));
}

export function addDays(date: string, days: number): string {
  const ms = dateMs(date);
  return Number.isNaN(ms) ? "" : new Date(ms + days * DAY_MS).toISOString().slice(0, 10);
}

/** 台北日曆的星期（0 = 星期一 … 6 = 星期日）。 */
export function weekdayIndex(date: string): number {
  const ms = dateMs(date);
  return Number.isNaN(ms) ? -1 : (new Date(ms).getUTCDay() + 6) % 7;
}

export function isMonday(date: string): boolean {
  return weekdayIndex(date) === 0;
}

/** 某日期所在週的星期一。 */
export function mondayOf(date: string): string {
  const i = weekdayIndex(date);
  return i < 0 ? "" : addDays(date, -i);
}

/** 某時間點（預設現在）所在的台北週一。 */
export function currentWeek(now: number = Date.now()): string {
  return mondayOf(taipeiDate(now));
}

export const WEEKDAY_LABELS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"];

/** `MM-DD`。 */
export function monthDay(date: string): string {
  return date.slice(5, 10);
}

/** 台北時間 `HH:MM`。 */
export function hhmm(value: unknown): string {
  return taipeiParts(value).slice(11, 16) || "—";
}

/** 台北時間 `YYYY-MM-DD HH:MM`；null 顯示「未設定」。 */
export function taipeiDateTime(value: unknown): string {
  if (value === null || value === undefined || value === "") return "未設定";
  const parts = taipeiParts(value);
  return parts ? parts.replace("T", " ") : "—";
}

export function durationMinutes(start: unknown, end: unknown): number {
  return Math.round((toMs(end) - toMs(start)) / 60_000);
}

/** 淨分鐘：max(0, 時段分鐘 − 休息)。 */
export function netMinutes(row: Rec): number {
  const brk = typeof row.break_minutes === "number" ? row.break_minutes : 0;
  const total = durationMinutes(row.start_at, row.end_at);
  return Number.isFinite(total) ? Math.max(0, total - brk) : 0;
}

export function formatMinutes(minutes: number): string {
  const sign = minutes < 0 ? "-" : "";
  const abs = Math.abs(minutes);
  const h = Math.floor(abs / 60);
  const m = abs % 60;
  return `${sign}${h} 小時 ${String(m).padStart(2, "0")} 分`;
}

export function isPast(value: unknown, now: number): boolean {
  const ms = toMs(value);
  return !Number.isNaN(ms) && ms <= now;
}

export function startMs(row: Rec): number {
  return toMs(row.start_at);
}

// ── 工作區中的行政資料 ────────────────────────────────────

export interface DeskData {
  units: Row[];
  staff: Row[];
  shifts: Row[];
  attendance: Row[];
  requests: Row[];
  equipment: Row[];
  reservations: Row[];
  notices: Row[];
  changes: Row[];
}

const COLLECTIONS = [
  "units",
  "staff",
  "shifts",
  "attendance",
  "requests",
  "equipment",
  "reservations",
  "notices",
  "changes",
] as const;

/** 由工作區快照取出 `administration`；未啟用時回傳 null。 */
export function deskOf(ws: Rec | null | undefined): DeskData | null {
  const raw = ws?.administration;
  if (!raw || typeof raw !== "object") return null;
  const src = raw as Rec;
  const out = {} as DeskData;
  for (const key of COLLECTIONS) {
    const v = src[key];
    out[key] = Array.isArray(v) ? (v.filter((r) => r && typeof r === "object" && typeof r.id === "string") as Row[]) : [];
  }
  return out;
}

export function deskIsEmpty(desk: DeskData): boolean {
  return COLLECTIONS.every((key) => desk[key].length === 0);
}

function byId(rows: Row[], id: unknown): Row | undefined {
  return typeof id === "string" ? rows.find((r) => r.id === id) : undefined;
}

export function unitOf(desk: DeskData, id: unknown): Row | undefined {
  return byId(desk.units, id);
}

export function staffOf(desk: DeskData, id: unknown): Row | undefined {
  return byId(desk.staff, id);
}

export function equipmentOf(desk: DeskData, id: unknown): Row | undefined {
  return byId(desk.equipment, id);
}

/** 找不到時的顯示名稱（A§6 備援）。 */
export function unitName(desk: DeskData, id: unknown): string {
  return str(unitOf(desk, id)?.name) || "原組織";
}

export function staffAlias(desk: DeskData, id: unknown): string {
  return str(staffOf(desk, id)?.alias) || "未指定";
}

export function equipmentName(desk: DeskData, id: unknown): string {
  return str(equipmentOf(desk, id)?.name) || "原設備";
}

export function activeUnits(desk: DeskData): Row[] {
  return desk.units.filter((u) => u.active === true);
}

/** 使用中且所屬組織也使用中的假員工。 */
export function activeStaff(desk: DeskData): Row[] {
  return desk.staff.filter((s) => s.status === "active" && unitOf(desk, s.unit_id)?.active === true);
}

/** 可借用（state = available）且組織使用中的設備。 */
export function bookableEquipment(desk: DeskData): Row[] {
  return desk.equipment.filter((e) => e.state === "available" && unitOf(desk, e.unit_id)?.active === true);
}

/** 依紀錄找所屬分頁的資料列。 */
export function rowsOfTab(desk: DeskData, tab: AdminTab): Row[] {
  return desk[tab];
}

/** 某筆紀錄的更正與保留紀錄（依時間排序）。 */
export function changesOf(desk: DeskData, recordId: string): Row[] {
  return desk.changes
    .filter((c) => c.record_id === recordId)
    .sort((a, b) => toMs(a.at) - toMs(b.at));
}

/** 卡片標題／儲存訊息用的紀錄名稱。 */
export function recordLabel(desk: DeskData, tab: AdminTab, row: Rec): string {
  switch (tab) {
    case "units":
    case "equipment":
      return str(row.name) || "未命名";
    case "staff":
      return str(row.alias) || str(row.code) || "假員工";
    case "shifts":
      return `${staffAlias(desk, row.staff_id)} ${taipeiDate(row.start_at)} 班次`;
    case "attendance":
      return `${staffAlias(desk, row.staff_id)} ${taipeiDate(row.start_at)} 出勤`;
    case "reservations":
      return `${equipmentName(desk, row.equipment_id)} 借用`;
    default:
      return str(row.title) || "未命名";
  }
}

// ── 伺服器檢視（GET /administration/...）────────────────────

export interface OverviewTile {
  id: string;
  label: string;
  value: number | string | null;
  unit: string | null;
  sub: string;
  target: { tab: string; unit?: string | null; type?: string; status?: string; q?: string | null };
}

export interface OnboardingStep {
  id: string;
  label: string;
  detail: string;
  done: boolean;
  reason: string;
  button: string;
}

export interface AdminOverview {
  now: string;
  week: string;
  tiles: OverviewTile[];
  onboarding: { steps: OnboardingStep[]; completed: number; open: boolean; summary: string };
  demo_empty: boolean;
  counts: Partial<Record<AdminTab, number>>;
}

export interface AdminRows {
  rows: Row[];
  summary: string;
  status_scope: string;
  period: string;
}

export interface DiffRow {
  staff_id: string;
  alias: string;
  scheduled: number;
  recorded: number;
  diff: number;
}

// ── CSV（列印用）───────────────────────────────────────────

/** 解析 RFC 4180 CSV（去掉 BOM，支援引號內換行與重複引號）。 */
export function parseCsv(text: string): string[][] {
  const src = text.charCodeAt(0) === 0xfeff ? text.slice(1) : text;
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < src.length; i += 1) {
    const ch = src[i];
    if (quoted) {
      if (ch === '"') {
        if (src[i + 1] === '"') {
          cell += '"';
          i += 1;
        } else quoted = false;
      } else cell += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ",") {
      row.push(cell);
      cell = "";
    } else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && src[i + 1] === "\n") i += 1;
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else cell += ch;
  }
  if (cell !== "" || row.length) {
    row.push(cell);
    rows.push(row);
  }
  return rows;
}

const GUARDED = /^'(?=[\s\x00-\x1f]*[=+\-@]|[\t\r])/;

/** CSV 為防公式注入在儲存格前加的 `'`，列印時拿掉。 */
export function unguard(cell: string): string {
  return cell.replace(GUARDED, "");
}

/** 每列前 12 欄是範圍欄（模式、工作區、版本…資料來源），其後是資料欄。 */
export const SCOPE_COLUMNS = 12;

export interface PrintData {
  tab: AdminTab;
  scope: [label: string, value: string][];
  headers: string[];
  rows: string[][];
}

/** 由匯出的 CSV 組出列印表：範圍欄取第一列的值，資料欄沿用 CSV 的表頭與內容。 */
export function printDataFromCsv(tab: AdminTab, csv: string): PrintData | null {
  const [head, ...body] = parseCsv(csv).filter((r) => r.length > 1 || (r[0] ?? "") !== "");
  if (!head || head.length < SCOPE_COLUMNS || body.length === 0) return null;
  const first = body[0];
  return {
    tab,
    scope: head.slice(0, SCOPE_COLUMNS).map((label, i) => [label, unguard(first[i] ?? "")]),
    headers: head.slice(SCOPE_COLUMNS),
    rows: body.map((r) => r.slice(SCOPE_COLUMNS).map(unguard)),
  };
}
