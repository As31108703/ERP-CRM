/** 備份匯出／匯入的前端預檢與還原階段（後端一次接收整份備份，上限 3 MiB）。 */

export const BACKUP_FORMAT = "erpcrm-sim-backup";
export const BACKUP_FILENAME = "erpcrm-sim-backup.json";
export const EXPORT_PATH = "/api/v1/backup/export";
export const IMPORT_PATH = "/api/v1/backup/import";

const MiB = 1024 * 1024;
export const FILE_LIMIT = 8 * MiB;
export const UPLOAD_LIMIT = 3 * MiB;

export const RESTORED_MESSAGE = "備份已完整檢查並還原，已建立新的資料世代。";

export type RestorePhase = "confirm" | "checking" | "uploading" | "verifying" | "done" | "failed";

/** 進度條依序顯示的四個階段。 */
export const RESTORE_STEPS: { phase: RestorePhase; label: string }[] = [
  { phase: "checking", label: "檢查" },
  { phase: "uploading", label: "上傳中" },
  { phase: "verifying", label: "伺服器驗證中" },
  { phase: "done", label: "完成" },
];

export interface BackupCandidate {
  fileName: string;
  /** 精簡後（無縮排）的 UTF-8 位元組數。 */
  bytes: number;
  companyName: string;
  industry: string;
  moduleCount: number;
  exportedAt: string;
  payload: Record<string, unknown>;
}

export type PrecheckResult = { ok: true; candidate: BackupCandidate } | { ok: false; error: string };

function readText(file: File): Promise<string> {
  if (typeof file.text === "function") return file.text();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error);
    reader.readAsText(file);
  });
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/**
 * 上傳前的檢查：檔案 ≤ 8 MiB、JSON 可解析、format 為星軌 SIM 備份、精簡後 ≤ 3 MiB。
 * 任一條件不符都不會送出請求。
 */
export async function precheckBackup(file: File): Promise<PrecheckResult> {
  if (file.size > FILE_LIMIT) return { ok: false, error: "檔案超過 8 MiB，無法匯入。" };
  let parsed: unknown;
  try {
    parsed = JSON.parse(await readText(file));
  } catch {
    return { ok: false, error: "無法解析這個檔案，請選擇匯出的 SIM JSON 備份。" };
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed) || (parsed as Record<string, unknown>).format !== BACKUP_FORMAT) {
    return { ok: false, error: "這個檔案不是星軌 SIM 備份，未做任何變更。" };
  }
  const payload = parsed as Record<string, unknown>;
  const bytes = new TextEncoder().encode(JSON.stringify(payload)).length;
  if (bytes > UPLOAD_LIMIT) return { ok: false, error: "備份精簡後超過 3 MiB，無法匯入。" };
  const meta = payload.workspace && typeof payload.workspace === "object" ? (payload.workspace as Record<string, unknown>) : {};
  return {
    ok: true,
    candidate: {
      fileName: file.name,
      bytes,
      companyName: text(meta.company_name),
      industry: text(meta.industry),
      moduleCount: Array.isArray(meta.modules) ? meta.modules.length : 0,
      exportedAt: text(payload.exported_at),
      payload,
    },
  };
}
