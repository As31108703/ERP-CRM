import { defineStore } from "pinia";
import { computed, hasInjectionContext, ref, watch } from "vue";
import { useRouter, type Router } from "vue-router";
import type { RoleViewId, TargetRef } from "../api/types";
import { findRow, isRecordKind, modulePath, moduleOfKind, RECORD_KINDS, targetLocation } from "../lib/records";
import { safeSession } from "../lib/storage";
import { useWorkspaceStore } from "./workspace";

export const PIN_LIMIT = 24;
export const PIN_LIMIT_MESSAGE = `最多釘選 ${PIN_LIMIT} 筆紀錄，請先取消一筆釘選。`;
const PIN_RAW_MAX = 16_384;
const PREF_RAW_MAX = 120;

export function pinsKey(generation: string): string {
  return `erpcrm.pins.v1.${encodeURIComponent(generation)}`;
}

export function roleViewKey(generation: string): string {
  return `erpcrm.role-view.v1.${encodeURIComponent(generation)}`;
}

export function firstRunKey(generation: string): string {
  return `erpcrm.first-run.v1.${encodeURIComponent(generation)}`;
}

/** 工作視角（F§5）。店長視角永遠可用，其他依後端 `roles[view].available`。 */
export const ROLE_VIEWS: { id: RoleViewId; name: string; description: string }[] = [
  { id: "owner", name: "店長／負責人", description: "掌握全店待辦與營運流程" },
  { id: "sales", name: "業務與服務", description: "跟進客戶、訂單與交付" },
  { id: "operations", name: "庫存與製造", description: "核對商品、材料與工單" },
  { id: "administration", name: "行政與排班", description: "處理班表與模擬行政申請" },
];

function isRoleView(value: unknown): value is RoleViewId {
  return typeof value === "string" && ROLE_VIEWS.some((r) => r.id === value);
}

function isPin(value: unknown): value is TargetRef {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return typeof v.module === "string" && typeof v.kind === "string" && typeof v.id === "string";
}

/** 讀 `{version:1, <field>}` 形式的偏好；格式不符回傳 undefined。 */
function readPref(key: string, field: string): unknown {
  const text = safeSession.get(key);
  if (!text || text.length > PREF_RAW_MAX) return undefined;
  try {
    const parsed: unknown = JSON.parse(text);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return undefined;
    const rec = parsed as Record<string, unknown>;
    return rec.version === 1 ? rec[field] : undefined;
  } catch {
    return undefined;
  }
}

/** 非單筆紀錄的頁面（行政、報表、教學、設定等）沒有 `/m/` 前綴。 */
export function moduleLocation(module: string): string {
  return modulePath(module);
}

/**
 * 介面狀態（每個工作區世代分開存在 sessionStorage，停用時退回記憶體）：
 * - 釘選：讀取時對照目前工作區，已刪除或模組未啟用的紀錄會被剔除。
 * - 工作視角：無效或不可用時退回店長視角。
 * - 上手引導收合狀態。
 * - 全域搜尋與快速新增的開關（兩者互斥；世代改變時關閉搜尋，世代或版本改變時關閉快速新增）。
 */
export const useUiStore = defineStore("ui", () => {
  const workspace = useWorkspaceStore();
  const router: Router | undefined = hasInjectionContext() ? useRouter() : undefined;

  const generation = computed(() => workspace.view?.workspace?.generation_id ?? "");
  const version = computed(() => workspace.view?.version ?? 0);

  // ── 釘選 ──────────────────────────────────────────────
  const raw = ref<TargetRef[]>([]);

  function loadPins(gen: string): TargetRef[] {
    if (!gen) return [];
    const text = safeSession.get(pinsKey(gen));
    if (!text || text.length > PIN_RAW_MAX) return [];
    try {
      const parsed: unknown = JSON.parse(text);
      return Array.isArray(parsed) ? parsed.filter(isPin).slice(0, PIN_LIMIT) : [];
    } catch {
      return [];
    }
  }

  /** 仍然有效的釘選：種類已知、模組正確且啟用、紀錄仍存在。 */
  const pins = computed(() => {
    const ws = workspace.view?.workspace;
    if (!ws) return [];
    return raw.value.filter(
      (p) =>
        isRecordKind(p.kind) &&
        p.module === moduleOfKind(p.kind, ws.modules) &&
        ws.modules.includes(p.module) &&
        findRow(ws, RECORD_KINDS[p.kind].collection, p.id) !== undefined,
    );
  });

  function isPinned(kind: string, id: string): boolean {
    return pins.value.some((p) => p.kind === kind && p.id === id);
  }

  function savePins(next: TargetRef[]): void {
    raw.value = next;
    if (generation.value) safeSession.set(pinsKey(generation.value), JSON.stringify(next));
  }

  /** 切換釘選；達上限時回傳提示訊息，成功回傳 null。 */
  function togglePin(target: TargetRef): string | null {
    const current = pins.value;
    if (current.some((p) => p.kind === target.kind && p.id === target.id)) {
      savePins(current.filter((p) => !(p.kind === target.kind && p.id === target.id)));
      return null;
    }
    if (current.length >= PIN_LIMIT) return PIN_LIMIT_MESSAGE;
    savePins([...current, { module: target.module, kind: target.kind, id: target.id }]);
    return null;
  }

  // ── 工作視角 ──────────────────────────────────────────
  const storedRole = ref<unknown>(undefined);

  function roleAvailable(id: RoleViewId): boolean {
    if (id === "owner") return true;
    return workspace.workbench?.roles?.[id]?.available === true;
  }

  const roleView = computed<RoleViewId>(() =>
    isRoleView(storedRole.value) && roleAvailable(storedRole.value) ? storedRole.value : "owner",
  );

  function setRoleView(id: RoleViewId): boolean {
    if (!isRoleView(id) || !roleAvailable(id)) return false;
    storedRole.value = id;
    if (generation.value) safeSession.set(roleViewKey(generation.value), JSON.stringify({ version: 1, view: id }));
    return true;
  }

  // ── 上手引導 ──────────────────────────────────────────
  const firstRunHidden = ref(false);
  /** 偏好只存在記憶體（storage 被停用）時為 true，介面會提示重新整理後不保留。 */
  const prefsVolatile = ref(safeSession.volatile);

  function setFirstRunHidden(hidden: boolean): void {
    firstRunHidden.value = hidden;
    if (generation.value) safeSession.set(firstRunKey(generation.value), JSON.stringify({ version: 1, hidden }));
    prefsVolatile.value = safeSession.volatile;
  }

  // ── 全域搜尋／快速新增 ────────────────────────────────
  const searchOpen = ref(false);
  const quickCreateOpen = ref(false);

  function openSearch(): boolean {
    if (!workspace.hasWorkspace) return false;
    quickCreateOpen.value = false;
    searchOpen.value = true;
    return true;
  }

  /** 快速新增：處理中、待確認或外觀試看時不開啟。 */
  function openQuickCreate(): boolean {
    if (!workspace.hasWorkspace || workspace.blockedReason()) return false;
    searchOpen.value = false;
    quickCreateOpen.value = true;
    return true;
  }

  function closeSearch(): void {
    searchOpen.value = false;
  }

  function closeQuickCreate(): void {
    quickCreateOpen.value = false;
  }

  watch(
    generation,
    (gen) => {
      raw.value = loadPins(gen);
      storedRole.value = gen ? readPref(roleViewKey(gen), "view") : undefined;
      firstRunHidden.value = gen ? readPref(firstRunKey(gen), "hidden") === true : false;
      prefsVolatile.value = safeSession.volatile;
      searchOpen.value = false;
    },
    { immediate: true },
  );

  watch([generation, version], () => {
    quickCreateOpen.value = false;
  });

  // ── 導覽 ──────────────────────────────────────────────
  /** 切到 target 所屬模組頁，以 `?target=<kind>:<id>` 交給 DataSection 定位。 */
  async function navigateTo(target: TargetRef): Promise<void> {
    searchOpen.value = false;
    quickCreateOpen.value = false;
    await router?.push(targetLocation(target));
  }

  /** 只開啟模組頁（角色流程、引導卡）。 */
  async function navigateModule(module: string): Promise<void> {
    searchOpen.value = false;
    quickCreateOpen.value = false;
    await router?.push(moduleLocation(module));
  }

  return {
    pins,
    isPinned,
    togglePin,
    roleView,
    roleAvailable,
    setRoleView,
    firstRunHidden,
    prefsVolatile,
    setFirstRunHidden,
    searchOpen,
    quickCreateOpen,
    openSearch,
    openQuickCreate,
    closeSearch,
    closeQuickCreate,
    navigateTo,
    navigateModule,
  };
});
