import { moduleLabel } from "../../lib/modules";

/** 模組以外的頁面名稱（角色流程與上手引導的步驟可能指向這些頁面）。 */
const PAGE_LABELS: Record<string, string> = {
  reports: "模擬報表",
  settings: "設定與資料",
  learning: "沉浸教學",
  capabilities: "功能地圖",
};

export function pageLabel(id: string): string {
  return PAGE_LABELS[id] ?? moduleLabel(id);
}
