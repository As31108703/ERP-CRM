/**
 * 星軌原創科幻主題。實際色彩 token 定義在 tokens.css，依
 * `<html data-theme-id data-theme data-density>` 選取；這裡是給主題圖庫用的描述資料，
 * `palette` 與 tokens.css 深色組的 bg／surface／ink／accent／accent-2 一致。
 */
export type ThemeId = "bridge" | "neon" | "orbital" | "quantum" | "foundry" | "nebula";
export type ThemeCategory = "command" | "trade" | "research" | "industrial";
export type PanelStyle = "notched" | "rounded" | "bracket";

export interface ThemeDef {
  id: ThemeId;
  name: string;
  englishName: string;
  category: ThemeCategory;
  description: string;
  signature: string;
  tags: [string, string, string];
  /** 背景、面板、文字、主強調、次強調 */
  palette: [string, string, string, string, string];
  panelStyle: PanelStyle;
  /** 標題字體（拉丁字母），中文一律退回 Noto Sans TC。 */
  displayFont: string;
}

export const DEFAULT_THEME: ThemeId = "bridge";

export const THEMES: readonly ThemeDef[] = [
  {
    id: "bridge",
    name: "深空艦橋",
    englishName: "Deep Space Bridge",
    category: "command",
    description: "冷青色儀表光暈配上琥珀警示，像在艦橋值班時盯著航道雷達。",
    signature: "切角面板 · 青色掃描線",
    tags: ["雷達", "冷色", "值班"],
    palette: ["#050913", "#0b1528", "#d6e6ff", "#38e1ff", "#ffb347"],
    panelStyle: "notched",
    displayFont: "Orbitron",
  },
  {
    id: "neon",
    name: "霓虹都會",
    englishName: "Neon Arcology",
    category: "trade",
    description: "洋紅與電光青交錯的夜市招牌色，適合節奏快的門市與訂單流。",
    signature: "括角框線 · 霓虹雙色",
    tags: ["夜城", "高對比", "交易"],
    palette: ["#0a0612", "#170c26", "#f6eaff", "#ff3fa4", "#35f2d0"],
    panelStyle: "bracket",
    displayFont: "Chakra Petch",
  },
  {
    id: "orbital",
    name: "軌道站",
    englishName: "Orbital Station",
    category: "command",
    description: "磷光綠讀數搭配穩定的鋼藍，像太空站維生系統的常駐面板。",
    signature: "圓角艙壁 · 磷光讀數",
    tags: ["維生", "穩定", "鋼藍"],
    palette: ["#060b10", "#0f1822", "#e2edf4", "#7cf3a0", "#6aa8ff"],
    panelStyle: "rounded",
    displayFont: "Exo 2",
  },
  {
    id: "quantum",
    name: "量子實驗室",
    englishName: "Quantum Lab",
    category: "research",
    description: "薄荷青與干涉紫在暗室中閃爍，給需要專注比對資料的時候。",
    signature: "切角面板 · 干涉紫光",
    tags: ["實驗", "精密", "冷光"],
    palette: ["#04080d", "#0a151c", "#dcfbf4", "#5cffd6", "#b48cff"],
    panelStyle: "notched",
    displayFont: "Rajdhani",
  },
  {
    id: "foundry",
    name: "星際鑄造廠",
    englishName: "Star Foundry",
    category: "industrial",
    description: "熔爐橘與高溫金黃壓在煤灰底色上，適合盯著工單與備料。",
    signature: "括角框線 · 熔爐餘燼",
    tags: ["熔爐", "暖色", "產線"],
    palette: ["#0d0907", "#1c1510", "#f6e7d7", "#ff8a3d", "#ffd166"],
    panelStyle: "bracket",
    displayFont: "Chakra Petch",
  },
  {
    id: "nebula",
    name: "星雲航道",
    englishName: "Nebula Lane",
    category: "research",
    description: "紫羅蘭星雲裡帶一點玫瑰粉，柔和但仍保有深空的距離感。",
    signature: "圓角艙壁 · 星雲柔光",
    tags: ["星雲", "柔和", "長時間"],
    palette: ["#080614", "#141031", "#ece8ff", "#9d7bff", "#ff7eb6"],
    panelStyle: "rounded",
    displayFont: "Exo 2",
  },
];

export const THEME_IDS: readonly ThemeId[] = THEMES.map((t) => t.id);

export const CATEGORY_LABELS: Record<ThemeCategory, string> = {
  command: "指揮",
  trade: "貿易",
  research: "研究",
  industrial: "工業",
};

export const PANEL_STYLE_LABELS: Record<PanelStyle, string> = {
  notched: "切角面板",
  rounded: "圓角艙壁",
  bracket: "括角框線",
};

export function isThemeId(value: unknown): value is ThemeId {
  return typeof value === "string" && (THEME_IDS as readonly string[]).includes(value);
}

export function themeById(id: ThemeId): ThemeDef {
  return THEMES.find((t) => t.id === id) ?? THEMES[0];
}
