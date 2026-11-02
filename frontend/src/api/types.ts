/** 後端回應型別。只列出前端骨架用得到的欄位，其餘集合以索引簽章保留。 */

export interface ErrorBody {
  error: { code: string; message: string; retry_after_ms?: number };
}

export interface WorkspaceSnapshot {
  generation_id: string;
  version: number;
  industry: string;
  company_name: string;
  modules: string[];
  template_version?: number;
  schema_version?: number;
  currency?: "SIM";
  simulation?: true;
  real_finance?: false;
  [collection: string]: unknown;
}

export interface WorkspaceView {
  workspace: WorkspaceSnapshot | null;
  csrf: string;
  version: number;
  retention_hours?: number | null;
  expires_at?: string | null;
  /** 後端 report(w)：`*_minor` 金額、`gross_profit_basis` 與選用的 `administration` 計數。 */
  report?: Record<string, unknown> | null;
}

export interface Template {
  id: string;
  name: string;
  purpose: string;
  modules: string[];
  version: number;
  sample?: unknown;
  terminology?: Record<string, string>;
  module_dependencies?: Record<string, string[]>;
  default_config?: Record<string, unknown>;
}

export interface TemplatesResponse {
  items: Template[];
  defaults: {
    industry: string;
    company_name: string;
    modules?: string[] | null;
    public_demo: boolean;
    auto_setup?: boolean;
    retention_hours: number | null;
  };
}

export interface TargetRef {
  module: string;
  kind: string;
  id: string;
}

/** 操作提示（F§2 Operation hints）。 */
export interface Readiness {
  summary: string;
  blockers: { message: string; target: TargetRef }[];
}

/** 待處理工作（F§2 Pending work queue）；attention 排在前面。 */
export interface QueueItem {
  id: string;
  target: TargetRef;
  title: string;
  description: string;
  priority: "attention" | "next";
  label: string;
}

/** 角色卡（F§5）：模組啟用才出現；target 為該種類第一筆符合的紀錄。 */
export interface RoleCard {
  id: string;
  label: string;
  module: string;
  count: number;
  unit: string;
  description: string;
  target?: TargetRef | null;
}

/** 角色流程：步驟只會開啟頁面。後端可回 `{module, label}` 或單純的模組字串。 */
export interface RoleFlow {
  id?: string;
  title: string;
  description?: string;
  steps: ({ module: string; label?: string } | string)[];
}

export interface RoleModel {
  available: boolean;
  cards: RoleCard[];
  flow: RoleFlow | null;
}

export type RoleViewId = "owner" | "sales" | "operations" | "administration";

export interface Workbench {
  readiness: Record<string, Readiness>;
  queue: QueueItem[];
  roles: Partial<Record<RoleViewId, RoleModel>>;
}

/** GET /api/v1/workbench/search：只含已啟用模組的紀錄。 */
export interface SearchItem {
  module: string;
  kind: string;
  id: string;
  title: string;
  description: string;
  status_label?: string | null;
}

export interface SearchResponse {
  total: number;
  items: SearchItem[];
}

/** GET /api/v1/workbench/first-run：三項上手進度與起點路線（F§4）。 */
export interface FirstRunItem {
  id: string;
  label: string;
  done: boolean;
}

export interface FirstRunRoute {
  module: string;
  title: string;
  description: string;
  action: string;
}

export interface FirstRun {
  progress: FirstRunItem[];
  route: FirstRunRoute | null;
  /** 可用的教學路線數；0 代表沒有。 */
  learning_available?: number;
}

/** 寫入命令的一般回應：`result` 為新紀錄 id 或 null，其餘為 view 欄位。 */
export interface MutationResult extends Partial<WorkspaceView> {
  result: string | null;
  replayed?: boolean;
  receipt?: { version: number };
}

/** 流程教學（Task 17 端點）。 */
export type LearningPathId = "sales" | "manufacturing" | "service";
export type LearningScope = "lesson" | "workspace";

/** 讀值；node 為所屬的流程示意圖節點 id（對應 `path.nodes`），不屬於任何節點時為 null。 */
export interface LearningFact {
  label: string;
  value: string;
  node: string | null;
}

export interface LearningCheckpoint {
  action: string;
  payload: Record<string, unknown>;
  result: string;
  version: number;
}

export interface LearningSession {
  id: string;
  path: LearningPathId;
  run_id: string;
  active: boolean;
  paused: boolean;
  scope: LearningScope;
  compact: boolean;
  quiz_choice: 0 | 1 | 2 | null;
  selected_step: string | null;
  created_at: string;
  updated_at: string;
}

export interface LearningStepEval {
  id: string;
  complete: boolean;
  evidence_text: string;
  checkpoint: LearningCheckpoint | null;
}

export interface LearningEvaluation {
  steps: LearningStepEval[];
  /** 第一個未完成步驟；全部完成時等於步驟數。 */
  next_index: number;
  complete: boolean;
}

export interface LearningSnapshot {
  version: number;
  result: string;
  rows: { label: string; before: string; after: string; node: string | null }[];
}

export interface LearningStepDef {
  id: string;
  action: string;
  title: string;
  body: string;
  change: string;
  nav: string;
  node: string;
}

export interface LearningPathDef {
  id: LearningPathId;
  title: string;
  subtitle: string;
  modules: string[];
  headline: string;
  intro: string;
  outcome: string;
  nodes: string[];
  steps: LearningStepDef[];
  quiz: { question: string; choices: string[]; answer: number; explanation: string };
}

export interface LearningDetail {
  path: LearningPathDef;
  session: LearningSession | null;
  evaluation: LearningEvaluation;
  /** 只針對 next_index 那一步；兩者恰有一個非 null。 */
  preview: { text: string | null; blocked_reason: string | null };
  facts: Record<LearningScope, LearningFact[]>;
  snapshots: Record<string, LearningSnapshot>;
}

export interface LearningListing {
  available_paths: LearningPathId[];
  sessions: { path: LearningPathId; run_id: string; confirmed: number; total: number }[];
  active: LearningPathId | null;
}

export type LearningViewPatch = Partial<Pick<LearningSession, "paused" | "scope" | "compact" | "quiz_choice" | "selected_step">>;
