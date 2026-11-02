import { matchesQuery, normalizeSearch } from "../../lib/search";
import { MODULE_ROUTES } from "../../router";

export type CapabilityStatus = "ready" | "partial" | "planned";

export interface CapabilityRoute {
  module: string;
  requires: string[];
}

export interface Capability {
  id: string;
  title: string;
  group: string;
  status: CapabilityStatus;
  /** 目前可以做到的範圍。 */
  available: string;
  /** 範圍與限制。 */
  gap: string;
  /** 前往的模組或頁面（MODULE_ORDER 之一或 router 的頁面名稱）；待建置項目沒有。 */
  module?: string;
  requires?: string[];
  /** 有多條可用路徑時依序取第一條需求齊全者。 */
  routes?: CapabilityRoute[];
  /** 對應的擴充藍圖項目 id。 */
  blueprint?: string;
}

export const CAPABILITY_GROUPS = [
  "上手與工作台",
  "財務與稅務",
  "客戶與銷售",
  "採購與庫存",
  "製造與服務",
  "人員與行政",
  "分析與平台",
  "延伸營運",
] as const;

export const CAPABILITY_STATUS_LABELS: Record<CapabilityStatus, string> = {
  ready: "已可用（SIM）",
  partial: "部分可用",
  planned: "待建置",
};

const G = CAPABILITY_GROUPS;

/**
 * 34 個工作領域與本專案（星軌 ERP-CRM）實際實作範圍的對照。
 * 狀態依本專案已完成的模組重新評估，不代表與任何商用系統功能相同。
 */
export const CAPABILITIES: Capability[] = [
  {
    id: "CAP01", title: "引導建置", group: G[0], status: "ready", module: "build",
    available: "三步驟建置精靈：命名、八種產業範本、推薦模組自動補齊相依，並可下載 docker compose 本機啟動包。",
    gap: "每個瀏覽器建立一個單人 SIM 工作區，沒有多人共用的租戶設定。",
  },
  {
    id: "CAP02", title: "角色工作視角", group: G[0], status: "ready", module: "overview",
    available: "店長、業務與服務、庫存與製造、行政與排班四種視角，各自顯示待辦卡與建議流程。",
    gap: "視角只是畫面偏好，沒有登入身分或權限控管。",
  },
  {
    id: "CAP03", title: "搜尋與操作引導", group: G[0], status: "ready", module: "overview",
    available: "Ctrl／Cmd+K 全站搜尋（全形半形皆可）、紀錄卡的卡關提示與前往處理連結、沉浸式流程教學。",
    gap: "搜尋只涵蓋本工作區的紀錄與本頁列出的功能。",
  },
  {
    id: "CAP04", title: "待辦與指標入口", group: G[0], status: "ready", module: "overview",
    available: "待處理工作分「需要先處理」與「可接續」，搭配釘選紀錄與報表摘要。",
    gap: "指標只來自 SIM 資料，沒有外部 BI 或排程寄送。",
  },
  {
    id: "CAP05", title: "總帳與結帳", group: G[1], status: "planned", blueprint: "gl",
    available: "尚未建置；目前只有測試幣錢包之間的移轉帳本。",
    gap: "需要會計科目、傳票、會計期間、試算表與月結鎖帳；測試幣帳本不能當總帳使用。",
  },
  {
    id: "CAP06", title: "應收帳款", group: G[1], status: "partial", module: "sales", blueprint: "ar",
    requires: ["sales", "wallets"],
    routes: [
      { module: "sales", requires: ["sales", "inventory", "wallets"] },
      { module: "services", requires: ["services", "crm", "wallets"] },
    ],
    available: "訂單可分次模擬付款，服務驗收後可分次以測試幣收款，未收金額看得到。",
    gap: "沒有應收科目、帳齡分析、客戶信用額度與收款沖銷。",
  },
  {
    id: "CAP07", title: "應付帳款", group: G[1], status: "planned", blueprint: "ap",
    available: "尚未建置；採購入庫只會從商家錢包直接付測試幣給供應商。",
    gap: "需要供應商帳單、付款條件、到期提醒與帳齡。",
  },
  {
    id: "CAP08", title: "銀行與資金對帳", group: G[1], status: "planned", blueprint: "treasury",
    available: "尚未建置；只有獨立的 SIM 測試幣流水。",
    gap: "需要模擬銀行帳戶、對帳單匯入、自動配對與差異處理，不會連線任何真實銀行。",
  },
  {
    id: "CAP09", title: "稅務與發票", group: G[1], status: "planned", blueprint: "tax",
    available: "尚未建置。",
    gap: "需要模擬稅額計算、發票草稿與作廢折讓流程、申報資料包；不會開立或申報真實發票。",
  },
  {
    id: "CAP10", title: "固定資產", group: G[1], status: "planned", blueprint: "assets",
    available: "行政工作台可以登記設備並處理借用預約。",
    gap: "沒有資產卡片、取得成本、折舊與處分分錄。",
  },
  {
    id: "CAP11", title: "客戶與商機", group: G[2], status: "ready", module: "crm", requires: ["crm"],
    available: "客戶、聯絡人、商機（失單須填原因）、跟進紀錄與案件。",
    gap: "單人模擬，沒有業務人員分派、郵件或通話整合。",
  },
  {
    id: "CAP12", title: "報價與產品配置", group: G[2], status: "partial", module: "crm", requires: ["crm"],
    available: "案件可建立報價草稿，發出後凍結並產生摘要，效期內以摘要模擬確認，舊版自動作廢。",
    gap: "沒有產品配置器、價目表分級與折扣規則。",
  },
  {
    id: "CAP13", title: "客服案件", group: G[2], status: "partial", module: "crm", requires: ["crm"],
    available: "客戶案件可串到報價、服務交付與補件紀錄。",
    gap: "沒有客服工單佇列、SLA 計時、知識庫或多通路收件。",
  },
  {
    id: "CAP14", title: "訂單與交付", group: G[2], status: "ready", module: "sales",
    requires: ["sales", "inventory", "wallets"],
    available: "多品項訂單預留庫存、分次付款、付清後分批出貨、部分退貨與出貨前取消。",
    gap: "全程 SIM，沒有物流商或金流服務串接。",
  },
  {
    id: "CAP15", title: "門市 POS", group: G[2], status: "planned",
    available: "尚未建置；可以先用模擬訂單練習銷售流程。",
    gap: "需要收銀畫面、班別結帳、掃碼與離線收款。",
  },
  {
    id: "CAP16", title: "採購與請購", group: G[3], status: "partial", module: "inventory", blueprint: "procurement",
    requires: ["inventory", "wallets"],
    routes: [
      { module: "inventory", requires: ["inventory", "wallets"] },
      { module: "administration", requires: ["administration"] },
    ],
    available: "商品可採購入庫並建立 FIFO 成本批次；行政工作台可提出請購申請並整理。",
    gap: "沒有正式採購單、供應商主檔與收貨／帳單／採購單三方比對。",
  },
  {
    id: "CAP17", title: "商品與 FIFO 庫存", group: G[3], status: "ready", module: "inventory", requires: ["inventory"],
    available: "商品目錄、FIFO 成本批次、可用／預留／現有三個數字，退貨回補到批次尾端。",
    gap: "只有一個總庫存，沒有效期或食安管理。",
  },
  {
    id: "CAP18", title: "倉庫與儲位", group: G[3], status: "planned", blueprint: "warehouse",
    available: "尚未建置；商品只記工作區的總庫存。",
    gap: "需要多倉庫、調撥、儲位、揀貨與盤點差異。",
  },
  {
    id: "CAP19", title: "BOM 與製造工單", group: G[4], status: "ready", module: "manufacturing",
    requires: ["manufacturing", "inventory", "wallets"],
    available: "有版本的 BOM（禁止循環）、工單備料、開工、完工以 FIFO 轉移成本，可取消並釋放材料。",
    gap: "沒有工作中心、產能排程、工時與製程檢驗。",
  },
  {
    id: "CAP20", title: "需求與補貨計畫", group: G[4], status: "planned", blueprint: "warehouse",
    available: "尚未建置；庫存頁可以查看目前可用數量。",
    gap: "需要安全庫存、需求預測、MRP 與自動補貨建議。",
  },
  {
    id: "CAP21", title: "服務交付與派工", group: G[4], status: "partial", module: "services",
    requires: ["services", "crm", "wallets"],
    available: "服務確認、提交交付版本、驗收或要求補件，驗收後分次收款。",
    gap: "沒有外勤派工、技師行程、工時紀錄或服務合約排程。",
  },
  {
    id: "CAP22", title: "專案與資源", group: G[4], status: "partial", module: "projects", requires: ["projects"],
    available: "任務與里程碑的狀態、到期時間，逾期自動標示，可關聯案件。",
    gap: "沒有資源負載、工時計費、專案預算與甘特圖。",
  },
  {
    id: "CAP23", title: "人資基本資料", group: G[5], status: "partial", module: "administration", blueprint: "hr",
    requires: ["administration"],
    available: "組織單位與假員工資料，可記錄任職狀態。",
    gap: "沒有真實人員敏感資料、招募、考核或員工自助。",
  },
  {
    id: "CAP24", title: "排班與出勤", group: G[5], status: "partial", module: "administration", blueprint: "hr",
    requires: ["administration"],
    available: "週班表（可整週複製）、手動出勤、附理由更正、出勤作廢與排班差異表。",
    gap: "沒有打卡設備、工時法規計算或主管核准權限。",
  },
  {
    id: "CAP25", title: "薪資與獎酬", group: G[5], status: "planned", blueprint: "payroll",
    available: "尚未建置。",
    gap: "需要模擬薪資結構、加扣項試算與覆核，不會產生真實薪資轉帳。",
  },
  {
    id: "CAP26", title: "費用與行政申請", group: G[5], status: "partial", module: "administration",
    requires: ["administration"],
    available: "請假、請購、費用與一般申請的草稿、送出、退回補件、撤回與整理。",
    gap: "整理完成不等於核准，沒有多層簽核或費用入帳。",
  },
  {
    id: "CAP27", title: "備份與資料追溯", group: G[6], status: "ready", module: "settings",
    available: "SIM JSON 匯出與完整驗證匯入、操作歷史、冪等收據與未確認操作的復原。",
    gap: "備份需自行保存，沒有雲端異地備份承諾。",
  },
  {
    id: "CAP28", title: "分析與預算", group: G[6], status: "partial", module: "reports", blueprint: "budget",
    available: "出貨、退貨、FIFO 成本與毛利、庫存價值、服務收款與行政指標。",
    gap: "沒有預算編列、預實比較、自訂查詢或資料倉儲。",
  },
  {
    id: "CAP29", title: "流程自動化", group: G[6], status: "planned",
    available: "尚未建置；每筆操作都由人工確認，可重送未確認的原操作。",
    gap: "需要排程、事件規則、Webhook 與流程編輯器。",
  },
  {
    id: "CAP30", title: "企業身份與整合", group: G[6], status: "planned",
    available: "尚未建置；工作區以瀏覽器 cookie 隔離，不需登入。",
    gap: "需要 SSO、多人權限、多公司合併與外部系統同步。",
  },
  {
    id: "CAP31", title: "電商與網站", group: G[7], status: "planned",
    available: "尚未建置；電商產業範本只提供模擬商品與訂單。",
    gap: "需要公開商店、購物車結帳與通路商品同步。",
  },
  {
    id: "CAP32", title: "批號、序號與條碼", group: G[7], status: "planned",
    available: "尚未建置；FIFO 批次只追蹤入庫成本。",
    gap: "成本批次不等於批號；需要序號、效期、條碼掃描與召回追溯。",
  },
  {
    id: "CAP33", title: "品質與維護", group: G[7], status: "planned", blueprint: "assets",
    available: "尚未建置；行政工作台可以登記設備與借用。",
    gap: "需要進料與成品檢驗、異常處理、保養排程與維修工單。",
  },
  {
    id: "CAP34", title: "日曆與預約", group: G[7], status: "partial", module: "administration",
    requires: ["administration"],
    available: "行政週班表與設備借用預約會檢查時間衝突，並可附理由更正。",
    gap: "沒有客戶預約、會議室排程或外部行事曆同步。",
  },
];

export const QUERY_MAX = 120;

function haystack(c: Capability): string {
  return normalizeSearch([c.id, c.title, c.group, c.available, c.gap].join(" "));
}

/** 依關鍵字（NFKC 分詞）、群組與狀態篩選；空字串代表不篩選。 */
export function filterCapabilities(query: string, group: string, status: string): Capability[] {
  return CAPABILITIES.filter(
    (c) => (!group || c.group === group) && (!status || c.status === status) && matchesQuery(haystack(c), query),
  );
}

/**
 * 前往目標：待建置或沒有模組 → null；沒有工作區 → build；
 * 有替代路徑時取第一條需求齊全者，否則 build；其餘需求齊全才前往模組。
 */
export function capabilityDestination(c: Capability, modules: string[] | null): string | null {
  if (c.status === "planned" || !c.module) return null;
  if (!modules) return "build";
  if (c.routes) return c.routes.find((r) => r.requires.every((m) => modules.includes(m)))?.module ?? "build";
  return (c.requires ?? []).every((m) => modules.includes(m)) ? c.module : "build";
}

/** 模組名稱 → 路由路徑：營運模組在 /m/ 底下，其餘（行政、報表、設定…）為頂層頁面。 */
export function destinationPath(destination: string): string {
  return (MODULE_ROUTES as readonly string[]).includes(destination) ? `/m/${destination}` : `/${destination}`;
}

export const REFERENCE_LINKS = [
  {
    label: "Business Central：角色中心設計",
    href: "https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/developer/devenv-designing-role-centers",
  },
  {
    label: "NetSuite 線上說明",
    href: "https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_1511800348.html",
  },
  { label: "Odoo 19 官方文件", href: "https://www.odoo.com/documentation/19.0/" },
] as const;
