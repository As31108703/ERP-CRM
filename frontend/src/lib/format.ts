/**
 * SIM 金額與時間的顯示／輸入轉換。金額一律以整數 minor 儲存，100 minor = 1 SIM；
 * 輸入以 SIM 為單位、最多兩位小數，換算只用字串與整數運算，避免浮點誤差。
 */

/** 後端整數上限（minor）。 */
export const SIM_MAX_MINOR = 1_000_000_000;

const GROUP = /\B(?=(\d{3})+(?!\d))/g;

/** 123456 → "1,234.56 SIM"。非整數或缺值視為 0。 */
export function formatSim(minor: number | null | undefined): string {
  const value = typeof minor === "number" && Number.isSafeInteger(minor) ? minor : 0;
  const abs = Math.abs(value);
  const whole = Math.floor(abs / 100).toString().replace(GROUP, ",");
  const cents = String(abs % 100).padStart(2, "0");
  return `${value < 0 ? "-" : ""}${whole}.${cents} SIM`;
}

const SIM_TEXT = /^(\d+)(?:\.(\d{1,2}))?$/;

/**
 * SIM 文字 → minor。接受全形數字、千分位逗號與結尾的「SIM」。
 * 負數、超過兩位小數、指數表示或超過上限時回傳 null。
 */
export function parseSim(text: string): number | null {
  const cleaned = text
    .normalize("NFKC")
    .trim()
    .replace(/\s*sim$/i, "")
    .replace(/,/g, "");
  const match = SIM_TEXT.exec(cleaned);
  if (!match) return null;
  const whole = match[1].replace(/^0+(?=\d)/, "");
  if (whole.length > 8) return null;
  const minor = Number(whole) * 100 + Number((match[2] ?? "").padEnd(2, "0"));
  return minor <= SIM_MAX_MINOR ? minor : null;
}

/** 表單預設值用：10000 → "100"、123450 → "1234.50"（不加千分位與單位）。 */
export function simInput(minor: number): string {
  const abs = Math.abs(Math.trunc(minor));
  const whole = Math.floor(abs / 100);
  const cents = abs % 100;
  return `${minor < 0 ? "-" : ""}${whole}${cents ? `.${String(cents).padStart(2, "0")}` : ""}`;
}

/** 以瀏覽器本地時區組出 `<input type="datetime-local">` 的值（到分鐘）。 */
export function toLocalInput(ms: number): string {
  const d = new Date(ms);
  if (Number.isNaN(d.valueOf())) return "";
  return new Date(d.valueOf() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

/** datetime-local 的值 → ISO 8601；無法解析時回傳 null。 */
export function localInputToIso(value: string): string | null {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(value)) return null;
  const d = new Date(value);
  return Number.isNaN(d.valueOf()) ? null : d.toISOString();
}

const DATE_TIME = new Intl.DateTimeFormat("zh-TW", {
  timeZone: "Asia/Taipei",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

/** ISO 時間以台北時區顯示，例如「2026/11/02 00:30」。無法解析時顯示「—」。 */
export function formatDateTime(iso: unknown): string {
  if (typeof iso !== "string") return "—";
  const ms = Date.parse(iso);
  return Number.isNaN(ms) ? "—" : DATE_TIME.format(ms);
}
