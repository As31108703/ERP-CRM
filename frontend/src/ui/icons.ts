/** 導覽軌用的線條圖示（24×24、stroke 繪製）。只放路徑資料，顏色跟隨 currentColor。 */
export const ICONS: Record<string, string> = {
  overview: "M3 12h4l2-6 4 12 2-6h6",
  learning: "M12 3 2 8l10 5 10-5-10-5Zm-6 7.5V16c0 1.7 2.7 3 6 3s6-1.3 6-3v-5.5",
  build: "M5 19 19 5m-9 0h9v9M5 5h2m-2 4h2",
  capabilities: "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Zm0 0v20M2 12h20M5 5c4 3 10 3 14 0M5 19c4-3 10-3 14 0",
  blueprint: "M4 4h16v16H4zM4 9h16M9 9v11",
  design: "M12 3a9 9 0 1 0 0 18c1 0 1.5-.8 1.2-1.6-.5-1.3.4-2.4 1.8-2.4H17a4 4 0 0 0 4-4c0-5.5-4-10-9-10Zm-5 9h.01M9 7h.01M15 7h.01",
  crm: "M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm-7 10c0-3.9 3.1-7 7-7s7 3.1 7 7m1-10a3 3 0 1 0 0-6m5 16c0-3-1.8-5.5-4-6.5",
  inventory: "M21 8 12 3 3 8v8l9 5 9-5V8Zm-18 0 9 5 9-5m-9 5v8",
  sales: "M3 4h2l2.5 11h11L21 7H6.5M9 20h.01M18 20h.01",
  wallets: "M3 7h15a3 3 0 0 1 3 3v7a3 3 0 0 1-3 3H3V7Zm0 0 12-3v3m2 7h.01",
  services: "M14 3H6v18h12V7l-4-4Zm0 0v4h4M9 13l2 2 4-4",
  manufacturing: "M3 21V10l6 4V10l6 4V4h6v17H3Zm4-4h2m4 0h2",
  projects: "M4 5h4v14H4zM10 5h4v9h-4zM16 5h4v6h-4z",
  administration: "M4 21V8l8-5 8 5v13M9 21v-6h6v6M4 21h16",
  reports: "M4 20V10m6 10V4m6 16v-7m4 7H2",
  settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm7.4-3a7.4 7.4 0 0 0-.1-1.3l2-1.6-2-3.4-2.4 1a7.4 7.4 0 0 0-2.2-1.3L14.4 3h-4l-.4 2.4a7.4 7.4 0 0 0-2.2 1.3l-2.4-1-2 3.4 2 1.6a7.4 7.4 0 0 0 0 2.6l-2 1.6 2 3.4 2.4-1a7.4 7.4 0 0 0 2.2 1.3l.4 2.4h4l.4-2.4a7.4 7.4 0 0 0 2.2-1.3l2.4 1 2-3.4-2-1.6c.1-.4.1-.9.1-1.3Z",
  search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14Zm5-2 5 5",
  plus: "M12 5v14M5 12h14",
  appearance: "M12 3v2m0 14v2M5.6 5.6l1.4 1.4m10 10 1.4 1.4M3 12h2m14 0h2M5.6 18.4 7 17M17 7l1.4-1.4M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z",
};

/** 營運模組的中文名稱（導覽軌與指令列共用）。 */
export const MODULE_LABELS: Record<string, string> = {
  crm: "客戶與商機",
  inventory: "商品庫存",
  sales: "模擬訂單",
  wallets: "測試幣流水",
  services: "報價與服務",
  manufacturing: "BOM 與製造",
  projects: "任務與里程碑",
};
