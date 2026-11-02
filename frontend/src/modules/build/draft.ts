import { safeSession, type SafeStorage } from "../../lib/storage";
import { COMPANY_MAX, MODULE_DEPENDENCIES, MODULE_ORDER } from "../../lib/modules";
import type { TemplatesResponse } from "../../api/types";

export type Destination = "public" | "local";

export interface BuilderDraft {
  industry: string;
  company: string;
  modules: string[];
  destination: Destination;
}

export const DRAFT_PREFIX = "erpcrm.builder.v1.";

type Defaults = TemplatesResponse["defaults"];
type Deps = Readonly<Record<string, readonly string[]>>;

function validModuleSet(value: unknown, deps: Deps): value is string[] {
  return (
    Array.isArray(value) &&
    value.length > 0 &&
    value.length <= MODULE_ORDER.length &&
    new Set(value).size === value.length &&
    value.every((m) => typeof m === "string" && (MODULE_ORDER as readonly string[]).includes(m)) &&
    value.every((m) => (deps[m] ?? []).every((d) => value.includes(d)))
  );
}

/** 依部署預設值與範本目錄產生初始草稿；公司名稱只在自架模式（public_demo=false）預填。 */
export function defaultDraft(templates: TemplatesResponse, deps: Deps = MODULE_DEPENDENCIES): BuilderDraft {
  const d: Defaults = templates.defaults;
  const template = templates.items.find((t) => t.id === d.industry) ?? templates.items[0];
  const modules = validModuleSet(d.modules, deps) ? [...d.modules] : [...(template?.modules ?? [])];
  const company =
    d.public_demo === false && typeof d.company_name === "string" && d.company_name.length <= COMPANY_MAX
      ? d.company_name
      : "";
  return { industry: template?.id ?? "", company, modules, destination: "public" };
}

/** 草稿依部署設定分開存放：預設值改變（例如切換公開試用）時不沿用舊草稿。 */
export function draftKey(templates: TemplatesResponse, deps: Deps = MODULE_DEPENDENCIES): string {
  const base = defaultDraft(templates, deps);
  const scope = {
    mode: templates.defaults.public_demo ? "public" : "local",
    industry: base.industry,
    modules: base.modules,
    company: base.company,
  };
  return DRAFT_PREFIX + encodeURIComponent(JSON.stringify(scope));
}

/** 嚴格驗證儲存的草稿；任何欄位不合格就整份捨棄。 */
export function parseDraft(raw: string | null, industryIds: readonly string[], deps: Deps = MODULE_DEPENDENCIES): BuilderDraft | null {
  if (!raw) return null;
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!data || typeof data !== "object" || Array.isArray(data)) return null;
  const d = data as Record<string, unknown>;
  const keys = Object.keys(d).sort().join(",");
  if (keys !== "company,destination,industry,modules") return null;
  if (typeof d.industry !== "string" || !industryIds.includes(d.industry)) return null;
  if (typeof d.company !== "string" || d.company.length > COMPANY_MAX) return null;
  if (!validModuleSet(d.modules, deps)) return null;
  if (d.destination !== "public" && d.destination !== "local") return null;
  return { industry: d.industry, company: d.company, modules: [...d.modules], destination: d.destination };
}

export function loadDraft(
  templates: TemplatesResponse,
  deps: Deps = MODULE_DEPENDENCIES,
  storage: SafeStorage = safeSession,
): BuilderDraft {
  const ids = templates.items.map((t) => t.id);
  return parseDraft(storage.get(draftKey(templates, deps)), ids, deps) ?? defaultDraft(templates, deps);
}

export function saveDraft(
  templates: TemplatesResponse,
  draft: BuilderDraft,
  deps: Deps = MODULE_DEPENDENCIES,
  storage: SafeStorage = safeSession,
): void {
  storage.set(draftKey(templates, deps), JSON.stringify(draft));
}

/** 設定頁「切換產業範本」清除後，帶著選好的範本前往自訂建置。 */
export function switchLocation(config: { industry: string; company: string; modules: string[] }) {
  return {
    path: "/custom",
    query: { industry: config.industry, company: config.company.trim(), modules: config.modules.join(",") },
  };
}

/** 由路由參數還原預選設定；與草稿同一套嚴格驗證，不合格時回傳 null。 */
export function draftFromQuery(
  query: Record<string, unknown>,
  industryIds: readonly string[],
  deps: Deps = MODULE_DEPENDENCIES,
): BuilderDraft | null {
  const { industry, company, modules } = query;
  if (typeof industry !== "string" || typeof modules !== "string") return null;
  const raw = JSON.stringify({
    industry,
    company: typeof company === "string" ? company : "",
    modules: modules === "" ? [] : modules.split(","),
    destination: "public",
  });
  return parseDraft(raw, industryIds, deps);
}
