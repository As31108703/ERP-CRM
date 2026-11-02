import { defineStore } from "pinia";
import { computed, ref, watch } from "vue";
import type { TargetRef } from "../api/types";
import { findRow, isRecordKind, moduleOfKind, RECORD_KINDS } from "../lib/records";
import { safeSession } from "../lib/storage";
import { useWorkspaceStore } from "./workspace";

export const PIN_LIMIT = 24;
export const PIN_LIMIT_MESSAGE = `最多釘選 ${PIN_LIMIT} 筆紀錄，請先取消一筆釘選。`;
const PIN_RAW_MAX = 16_384;

export function pinsKey(generation: string): string {
  return `erpcrm.pins.v1.${encodeURIComponent(generation)}`;
}

function isPin(value: unknown): value is TargetRef {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return typeof v.module === "string" && typeof v.kind === "string" && typeof v.id === "string";
}

/**
 * 介面狀態（每個工作區世代分開存）。目前提供釘選；Task 21 會在此加入角色視角與上手引導。
 * 釘選存在 sessionStorage（停用時退回記憶體），讀取時對照目前工作區，已刪除或模組未啟用的紀錄會被剔除。
 */
export const useUiStore = defineStore("ui", () => {
  const workspace = useWorkspaceStore();
  const raw = ref<TargetRef[]>([]);

  const generation = computed(() => workspace.view?.workspace?.generation_id ?? "");

  function load(gen: string): TargetRef[] {
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

  watch(generation, (gen) => (raw.value = load(gen)), { immediate: true });

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

  function save(next: TargetRef[]): void {
    raw.value = next;
    if (generation.value) safeSession.set(pinsKey(generation.value), JSON.stringify(next));
  }

  /** 切換釘選；達上限時回傳提示訊息，成功回傳 null。 */
  function togglePin(target: TargetRef): string | null {
    const current = pins.value;
    if (current.some((p) => p.kind === target.kind && p.id === target.id)) {
      save(current.filter((p) => !(p.kind === target.kind && p.id === target.id)));
      return null;
    }
    if (current.length >= PIN_LIMIT) return PIN_LIMIT_MESSAGE;
    save([...current, { module: target.module, kind: target.kind, id: target.id }]);
    return null;
  }

  return { pins, isPinned, togglePin };
});
