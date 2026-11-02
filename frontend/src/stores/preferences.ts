import { defineStore } from "pinia";
import { computed, ref, watchSyncEffect } from "vue";
import { safeLocal } from "../lib/storage";
import { DEFAULT_THEME, isThemeId, themeById, type ThemeId } from "../themes/themes";
import { useWorkspaceStore } from "./workspace";

export const THEME_KEY = "erpcrm.theme.v1";
export const INTERFACE_KEY = "erpcrm.interface.v1";
const INTERFACE_MAX = 256;

export type SchemePref = "system" | "light" | "dark";
export type Density = "comfortable" | "compact";

const SCHEMES: readonly SchemePref[] = ["system", "light", "dark"];
const DENSITIES: readonly Density[] = ["comfortable", "compact"];

function readTheme(): ThemeId {
  try {
    const raw = safeLocal.get(THEME_KEY);
    if (!raw) return DEFAULT_THEME;
    const data = JSON.parse(raw) as unknown;
    if (data && typeof data === "object" && !Array.isArray(data)) {
      const { version, theme } = data as Record<string, unknown>;
      if (version === 1 && isThemeId(theme)) return theme;
    }
  } catch {
    /* 格式錯誤：退回預設 */
  }
  return DEFAULT_THEME;
}

function readInterface(): { theme: SchemePref; density: Density } {
  const fallback = { theme: "system" as SchemePref, density: "comfortable" as Density };
  try {
    const raw = safeLocal.get(INTERFACE_KEY);
    if (!raw || raw.length > INTERFACE_MAX) return fallback;
    const data = JSON.parse(raw) as unknown;
    if (!data || typeof data !== "object" || Array.isArray(data)) return fallback;
    const keys = Object.keys(data).sort();
    if (keys.length !== 2 || keys[0] !== "density" || keys[1] !== "theme") return fallback;
    const { theme, density } = data as Record<string, unknown>;
    if (!SCHEMES.includes(theme as SchemePref) || !DENSITIES.includes(density as Density)) return fallback;
    return { theme: theme as SchemePref, density: density as Density };
  } catch {
    return fallback;
  }
}

/** 寫入後讀回比對；不一致或失敗時回傳 false，介面改提示「只保留在本分頁」。 */
function writeVerified(key: string, value: string): boolean {
  safeLocal.set(key, value);
  return !safeLocal.volatile && safeLocal.get(key) === value;
}

function systemPrefersDark(): MediaQueryList | null {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return null;
  return window.matchMedia("(prefers-color-scheme: dark)");
}

/** Esc 取消試看的排除條件：焦點在可輸入元素，或畫面上有開著的對話框。 */
function escapeBlocked(event: KeyboardEvent): boolean {
  const target = event.target;
  if (target instanceof HTMLElement) {
    if (target.isContentEditable || target.closest("input, textarea, select, [contenteditable='true']")) {
      return true;
    }
  }
  return typeof document !== "undefined" && document.querySelector("[data-erpcrm-dialog]") !== null;
}

export const usePreferencesStore = defineStore("preferences", () => {
  const workspace = useWorkspaceStore();

  const themeId = ref<ThemeId>(readTheme());
  const previewId = ref<ThemeId | null>(null);
  const initial = readInterface();
  const scheme = ref<SchemePref>(initial.theme);
  const density = ref<Density>(initial.density);
  const persisted = ref(!safeLocal.volatile);

  const media = systemPrefersDark();
  const systemDark = ref(media ? media.matches : true);
  media?.addEventListener?.("change", (e) => {
    systemDark.value = e.matches;
  });

  const previewing = computed(() => previewId.value !== null);
  const activeThemeId = computed<ThemeId>(() => previewId.value ?? themeId.value);
  const resolvedScheme = computed<"light" | "dark">(() =>
    scheme.value === "dark" || (scheme.value === "system" && systemDark.value) ? "dark" : "light",
  );
  const theme = computed(() => themeById(themeId.value));
  const previewTheme_ = computed(() => (previewId.value ? themeById(previewId.value) : null));

  /** 不會被 Esc 取消試看的單次導覽（「到工作台看效果」）。 */
  let keepPreviewOnce = false;

  watchSyncEffect(() => {
    if (typeof document === "undefined") return;
    const ds = document.documentElement.dataset;
    ds.themeId = activeThemeId.value;
    ds.theme = resolvedScheme.value;
    ds.density = density.value;
  });

  function previewTheme(id: ThemeId): void {
    if (!isThemeId(id)) return;
    previewId.value = id === themeId.value ? null : id;
    workspace.setDesignPreview(previewId.value !== null);
  }

  function cancelPreview(): void {
    previewId.value = null;
    keepPreviewOnce = false;
    workspace.setDesignPreview(false);
  }

  function applyTheme(id: ThemeId): void {
    if (!isThemeId(id)) return;
    themeId.value = id;
    persisted.value = writeVerified(THEME_KEY, JSON.stringify({ version: 1, theme: id }));
    cancelPreview();
    const name = themeById(id).name;
    workspace.message = persisted.value
      ? `已套用「${name}」，外觀保留在這個瀏覽器。`
      : `已套用「${name}」，外觀目前只保留在本分頁。`;
  }

  function saveInterface(): void {
    persisted.value = writeVerified(
      INTERFACE_KEY,
      JSON.stringify({ theme: scheme.value, density: density.value }),
    );
  }

  function setScheme(value: SchemePref): void {
    if (!SCHEMES.includes(value)) return;
    scheme.value = value;
    saveInterface();
  }

  function setDensity(value: Density): void {
    if (!DENSITIES.includes(value)) return;
    density.value = value;
    saveInterface();
  }

  /** 「到工作台看效果」：保留試看並允許下一次離開主題圖庫的導覽。 */
  function keepPreviewForNextNavigation(): void {
    keepPreviewOnce = previewing.value;
  }

  /**
   * 每次導覽完成後由路由呼叫：前往主題圖庫以外的頁面一律取消試看，
   * 唯一例外是「到工作台看效果」那一次導覽（保留旗標在這一次就清除）。
   */
  function navigated(toName: string): void {
    if (toName === "design") return;
    if (keepPreviewOnce) {
      keepPreviewOnce = false;
      return;
    }
    if (previewing.value) cancelPreview();
  }

  if (typeof window !== "undefined") {
    window.addEventListener("keydown", (event) => {
      if (event.key !== "Escape" || !previewing.value || escapeBlocked(event)) return;
      cancelPreview();
    });
  }

  return {
    themeId,
    previewId,
    scheme,
    density,
    persisted,
    previewing,
    activeThemeId,
    resolvedScheme,
    theme,
    previewThemeDef: previewTheme_,
    previewTheme,
    applyTheme,
    cancelPreview,
    setScheme,
    setDensity,
    keepPreviewForNextNavigation,
    navigated,
  };
});
