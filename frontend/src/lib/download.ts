import { ApiError, decodeError, inflight } from "../api/client";

/** 物件網址保留一下再釋放，讓瀏覽器有時間開始下載。 */
export const REVOKE_DELAY_MS = 1000;

/**
 * 下載檔案：先以 fetch 取得內容，非 2xx 時解出錯誤訊息（不把錯誤 JSON 存成檔案），
 * 成功才轉成 Blob 交給暫時的 `<a download>`。回傳 null 表示成功，否則為錯誤訊息。
 */
export async function downloadFile(url: string, filename: string): Promise<string | null> {
  inflight.value++;
  try {
    let res: Response;
    try {
      res = await fetch(url, { credentials: "same-origin" });
    } catch {
      return new ApiError(0, "network_error", "無法連線到伺服器，請確認網路後再試。").message;
    }
    if (!res.ok) return (await decodeError(res)).message;
    let blob: Blob;
    try {
      blob = await res.blob();
    } catch {
      return "下載內容讀取失敗，請再試一次。";
    }
    const href = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = href;
    a.download = filename;
    a.rel = "noopener";
    a.style.display = "none";
    document.body.appendChild(a);
    try {
      a.click();
    } finally {
      a.remove();
      setTimeout(() => URL.revokeObjectURL(href), REVOKE_DELAY_MS);
    }
    return null;
  } finally {
    inflight.value--;
  }
}

/**
 * 以同樣的 fetch 與錯誤解碼規則讀取文字內容（例如列印前取得匯出的 CSV）。
 * 成功回傳 `{ text }`，失敗回傳 `{ error }`。
 */
export async function fetchText(url: string): Promise<{ text: string } | { error: string }> {
  inflight.value++;
  try {
    let res: Response;
    try {
      res = await fetch(url, { credentials: "same-origin" });
    } catch {
      return { error: new ApiError(0, "network_error", "無法連線到伺服器，請確認網路後再試。").message };
    }
    if (!res.ok) return { error: (await decodeError(res)).message };
    try {
      return { text: await res.text() };
    } catch {
      return { error: "內容讀取失敗，請再試一次。" };
    }
  } finally {
    inflight.value--;
  }
}
