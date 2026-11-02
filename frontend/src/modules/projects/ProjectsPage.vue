<script setup lang="ts">
import { computed } from "vue";
import { formatDateTime, toLocalInput } from "../../lib/format";
import { findRow, recordName, statusKey, statusLabel, str, type Row } from "../../lib/records";
import DataSection from "../../ui/DataSection.vue";
import EmptyState from "../../ui/EmptyState.vue";
import RecordCard from "../../ui/RecordCard.vue";
import { API_V1, useCommandForm, type CommandFormSpec } from "../shared/commandForm";
import CommandDialog from "../shared/CommandDialog.vue";
import {
  PROJECT_COLLECTION,
  PROJECT_LABEL,
  projectCreateSpec,
  projectFields,
  readProjectCommon,
  type ProjectKind,
} from "../shared/createForms";
import PageHead from "../shared/PageHead.vue";
import { usePage } from "../shared/usePage";

type Kind = ProjectKind;

const CLOSED = ["done", "completed", "cancelled"];

const { store, ws, resetKey, rows, enabled, readiness, targetId, clearTarget, searchText } = usePage();
const form = useCommandForm();

const tasks = computed(() => rows("tasks"));
const milestones = computed(() => rows("milestones"));

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

function createSpec(kind: Kind): CommandFormSpec {
  return projectCreateSpec(kind, ws.value);
}

function updateSpec(kind: Kind, row: Row): CommandFormSpec {
  return {
    title: `更新${PROJECT_LABEL[kind]}進度`,
    fields: projectFields(kind, str(row, "status")),
    initial: { title: str(row, "title"), status: str(row, "status"), due_at: dueInput(row), notes: str(row, "notes") },
    submitLabel: "儲存進度",
    build: (v) => {
      const common = readProjectCommon(v);
      if (typeof common === "string") return common;
      return { method: "PATCH", path: `${API_V1}/projects/${PROJECT_COLLECTION[kind]}/${encodeURIComponent(row.id)}`, body: common };
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
            <template #title>{{ recordName(item, PROJECT_LABEL[s.kind]) }}</template>
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
