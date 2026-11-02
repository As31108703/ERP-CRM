import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import { normalizeSearch } from "../../lib/search";
import { recordName, rowsOf, statusLabel, statusKey, targetIdFor, type Row } from "../../lib/records";
import { useWorkspaceStore } from "../../stores/workspace";

/** 模組頁共用：目前快照、操作提示、路由定位與搜尋字串。 */
export function usePage() {
  const store = useWorkspaceStore();
  const route = useRoute();
  const router = useRouter();

  const ws = computed(() => store.view?.workspace ?? null);
  const modules = computed(() => ws.value?.modules ?? []);
  const resetKey = computed(() => ws.value?.generation_id ?? "");

  function rows(collection: string): Row[] {
    return rowsOf(ws.value, collection);
  }

  function enabled(module: string): boolean {
    return modules.value.includes(module);
  }

  function readiness(kind: string, id: string) {
    return store.workbench?.readiness?.[`${kind}:${id}`] ?? null;
  }

  function targetId(kind: string): string | null {
    return targetIdFor(route.query.target, kind);
  }

  /** 使用者自行搜尋、篩選或換頁時清除定位參數。 */
  function clearTarget(): void {
    if (route.query.target === undefined) return;
    const query = { ...route.query };
    delete query.target;
    void router.replace({ query });
  }

  /** 搜尋字串：標題、狀態文字、相關紀錄名稱與常用文字欄位。 */
  function searchText(kind: string, row: Row, related: (string | undefined)[] = []): string {
    const parts = [recordName(row), statusLabel(statusKey(kind, row)), ...related];
    for (const key of ["name", "title", "sku", "notes", "email", "phone", "lost_reason"]) {
      const v = row[key];
      if (typeof v === "string") parts.push(v);
    }
    return normalizeSearch(parts.filter(Boolean).join(" "));
  }

  return { store, ws, modules, resetKey, rows, enabled, readiness, targetId, clearTarget, searchText };
}
