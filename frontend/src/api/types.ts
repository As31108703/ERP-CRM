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
  report?: Record<string, number> | null;
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
}

export interface TemplatesResponse {
  items: Template[];
  defaults: {
    industry: string;
    company_name: string;
    modules?: string[];
    public_demo: boolean;
    retention_hours: number | null;
  };
}

export interface TargetRef {
  module: string;
  kind: string;
  id: string;
}

export interface Workbench {
  readiness: Record<string, { summary: string; blockers: { message: string; target: TargetRef }[] }>;
  queue: { id: string; target: TargetRef; title: string; description: string; priority: number; label: string }[];
  roles: Record<
    string,
    { available: boolean; cards: unknown[]; flow: { title: string; steps: unknown[] } }
  >;
}

/** 寫入命令的一般回應：`result` 為新紀錄 id 或 null，其餘為 view 欄位。 */
export interface MutationResult extends Partial<WorkspaceView> {
  result: string | null;
  replayed?: boolean;
  receipt?: { version: number };
}
