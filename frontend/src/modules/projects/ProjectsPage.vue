<script setup lang="ts">
import { computed } from "vue";
import { formatDateTime, localInputToIso, toLocalInput } from "../../lib/format";
import { findRow, recordName, statusKey, statusLabel, str, type Row } from "../../lib/records";
import DataSection from "../../ui/DataSection.vue";
import EmptyState from "../../ui/EmptyState.vue";
import type { FormField } from "../../ui/FormDialog.vue";
import RecordCard from "../../ui/RecordCard.vue";
import { API_V1, useCommandForm, type CommandFormSpec, type FormValues } from "../shared/commandForm";
import CommandDialog from "../shared/CommandDialog.vue";
import { options } from "../shared/createForms";
import PageHead from "../shared/PageHead.vue";
import { usePage } from "../shared/usePage";

type Kind = "task" | "milestone";

const COLLECTION: Record<Kind, string> = { task: "tasks", milestone: "milestones" };
const LABEL: Record<Kind, string> = { task: "任務", milestone: "里程碑" };
const CLOSED = ["done", "completed", "cancelled"];

const { store, ws, resetKey, rows, enabled, readiness, targetId, clearTarget, searchText } = usePage();
const form = useCommandForm();

const tasks = computed(() => rows("tasks"));
const milestones = computed(() => rows("milestones"));

function statusOptions(kind: Kind, current = ""): { value: string; label: string }[] {
  const values = ["todo", "in_progress", "done", ...(kind === "milestone" ? ["planned"] : [])];
  if (current && !values.includes(current)) values.push(current);
  return values.map((v) => ({ value: v, label: statusLabel(v) }));
}

function caseTitle(row: Row): string {
  const c = findRow(ws.value, "cases", row.case_id);
  return c ? recordName(c, "案件") : "一般工作";
}

function overdue(row: Row): boolean {
  const due = Date.parse(str(row, "due_at"));
  return !Number.isNaN(due) && !CLOSED.includes(str(row, "status")) && due < Date.now();
}

function dueInput(row: Row): string {
  const due = Date.parse(str(row, "due_at"));
  return Number.isNaN(due) ? "" : toLocalInput(due);
}

/** 共用欄位轉換：空白到期時間送 null，其餘以本地時間換算 ISO。 */
function readCommon(v: FormValues): { title: string; status: string; due_at: string | null; notes: string } | string {
  const raw = String(v.due_at ?? "");
  const due = raw === "" ? null : localInputToIso(raw);
  if (raw !== "" && due === null) return "到期時間格式不正確。";
  return { title: String(v.title), status: String(v.status), due_at: due, notes: String(v.notes ?? "") };
}

function baseFields(kind: Kind, current = ""): FormField[] {
  return [
    { name: "title", label: "標題", required: true, maxlength: 200 },
    { name: "status", label: "狀態", type: "select", required: true, options: statusOptions(kind, current) },
    { name: "due_at", label: "到期時間", type: "datetime-local", hint: "留白表示未設定" },
    { name: "notes", label: "備註", type: "textarea" },
  ];
}

function createSpec(kind: Kind): CommandFormSpec {
  const cases = rows("cases");
  const fields = baseFields(kind);
  if (cases.length) fields.push({ name: "case_id", label: "關聯案件（選填）", type: "select", options: options(cases, "案件") });
  return {
    title: `新增${LABEL[kind]}`,
    fields,
    initial: { status: kind === "task" ? "todo" : "planned" },
    submitLabel: `建立${LABEL[kind]}`,
    build: (v) => {
      const common = readCommon(v);
      if (typeof common === "string") return common;
      const body: Record<string, unknown> = { ...common };
      if (typeof v.case_id === "string" && v.case_id !== "") body.case_id = v.case_id;
      return { method: "POST", path: `${API_V1}/projects/${COLLECTION[kind]}`, body };
    },
  };
}

function updateSpec(kind: Kind, row: Row): CommandFormSpec {
  return {
    title: `更新${LABEL[kind]}進度`,
    fields: baseFields(kind, str(row, "status")),
    initial: { title: str(row, "title"), status: str(row, "status"), due_at: dueInput(row), notes: str(row, "notes") },
    submitLabel: "儲存進度",
    build: (v) => {
      const common = readCommon(v);
      if (typeof common === "string") return common;
      return { method: "PATCH", path: `${API_V1}/projects/${COLLECTION[kind]}/${encodeURIComponent(row.id)}`, body: common };
    },
  };
}

function search(kind: Kind) {
  return (row: Row) => searchText(kind, row, [caseTitle(row)]);
}

const SECTIONS = computed(() => [
  { kind: "task" as const, title: "任務", code: "TSK-BOARD", items: tasks.value, empty: "還沒有任務。新增第一個任務並設定到期時間。" },
  { kind: "milestone" as const, title: "里程碑", code: "MLS-TRACK", items: milestones.value, empty: "還沒有里程碑。新增一個階段目標。" },
]);
</script>

<template>
  <div class="mpage" data-testid="page-projects">
    <PageHead code="MODULE · PROJECTS · TRK" title="專案" lead="任務與里程碑記錄狀態與到期時間；未完成且超過到期時間的項目會標示逾期。">
      <button type="button" class="btn" data-testid="create-task" :disabled="store.busy" @click="form.open(createSpec('task'))">
        新增任務
      </button>
      <button
        type="button"
        class="btn btn--primary"
        data-testid="create-milestone"
        :disabled="store.busy"
        @click="form.open(createSpec('milestone'))"
      >
        新增里程碑
      </button>
    </PageHead>

    <EmptyState v-if="!enabled('projects')" title="尚未啟用此模組" text="請到設定頁切換產業範本或調整模組。" />
    <div v-else class="mpage__grid">
      <DataSection
        v-for="s in SECTIONS"
        :key="s.kind"
        :title="s.title"
        :code="s.code"
        :items="s.items"
        :search-text="search(s.kind)"
        :status-of="(r: Row) => statusKey(s.kind, r)"
        :status-label="statusLabel"
        :target-id="targetId(s.kind)"
        :reset-key="resetKey"
        :empty-text="s.empty"
        @clear-target="clearTarget"
      >
        <template #item="{ item }">
          <RecordCard :kind="s.kind" :row="item" :readiness="readiness(s.kind, item.id)">
            <template #title>{{ recordName(item, LABEL[s.kind]) }}</template>
            <p class="mpage__dim">{{ caseTitle(item) }}<template v-if="str(item, 'notes')"> · {{ str(item, "notes") }}</template></p>
            <p v-if="str(item, 'due_at')" class="proj__due" :class="{ overdue: overdue(item) }">
              到期：<span class="num">{{ formatDateTime(item.due_at) }}</span><template v-if="overdue(item)"> · 已逾期</template>
            </p>
            <p v-else class="proj__due mpage__dim">未設定到期時間</p>
            <template #actions>
              <button type="button" class="btn btn--sm" :disabled="store.busy" @click="form.open(updateSpec(s.kind, item))">
                更新進度
              </button>
            </template>
          </RecordCard>
        </template>
      </DataSection>
    </div>

    <CommandDialog :form="form" />
  </div>
</template>

<style scoped src="../shared/page.css"></style>
<style scoped>
.proj__due {
  margin: 0;
  font-size: 0.9rem;
}
.proj__due.overdue {
  color: var(--danger);
}
</style>
