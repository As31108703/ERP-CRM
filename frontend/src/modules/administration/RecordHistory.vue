<script setup lang="ts">
import { computed } from "vue";
import type { Row } from "../../lib/records";
import { taipeiDateTime } from "./adminModel";

/**
 * 更正與保留紀錄（A§5「History panel」）：每筆顯示種類、台北時間與原因，
 * 再以「欄位／更正前／更正後」三欄表比對差異。沒有紀錄時不顯示。
 */
const props = defineProps<{ changes: Row[] }>();

const KIND_LABELS: Record<string, string> = {
  "shift.update": "班次時段更正",
  "attendance.update": "手動出勤更正",
  "attendance.void": "手動出勤作廢",
  "reservation.update": "設備預約更改",
  "notice.archive": "公告封存",
  "notice.restore": "公告還原",
};

type Field = [key: string, label: string, kind: "time" | "minutes" | "text" | "flag"];

const SEGMENT: Field[] = [
  ["start_at", "開始", "time"],
  ["end_at", "結束", "time"],
  ["break_minutes", "休息分鐘", "minutes"],
  ["note", "備註", "text"],
];

function fieldsOf(kind: string): Field[] {
  if (kind.startsWith("shift.")) return SEGMENT;
  if (kind.startsWith("attendance.")) return [...SEGMENT, ["voided", "作廢", "flag"]];
  if (kind.startsWith("reservation.")) {
    return [
      ["start_at", "開始", "time"],
      ["end_at", "結束", "time"],
      ["purpose", "借用用途", "text"],
    ];
  }
  return [
    ["archived", "封存", "flag"],
    ["pinned", "置頂", "flag"],
    ["due_at", "截止時間", "time"],
  ];
}

function show(value: unknown, kind: Field[2]): string {
  if (kind === "time") return taipeiDateTime(value);
  if (kind === "flag") return value === true ? "是" : "否";
  if (kind === "minutes") return typeof value === "number" ? `${value} 分` : "—";
  return typeof value === "string" && value !== "" ? value : "（空白）";
}

function snapshot(change: Row, side: "before" | "after"): Record<string, unknown> {
  const v = change[side];
  return v && typeof v === "object" ? (v as Record<string, unknown>) : {};
}

const entries = computed(() =>
  props.changes.map((c) => {
    const kind = typeof c.kind === "string" ? c.kind : "";
    const before = snapshot(c, "before");
    const after = snapshot(c, "after");
    return {
      id: c.id,
      label: KIND_LABELS[kind] ?? "紀錄更正",
      at: taipeiDateTime(c.at),
      reason: typeof c.reason === "string" ? c.reason : "",
      rows: fieldsOf(kind).map(([key, label, type]) => ({
        key,
        label,
        before: show(before[key], type),
        after: show(after[key], type),
        changed: JSON.stringify(before[key] ?? null) !== JSON.stringify(after[key] ?? null),
      })),
    };
  }),
);
</script>

<template>
  <details v-if="entries.length" class="rhist" data-testid="record-history">
    <summary>更正與保留紀錄 <span class="num">（{{ entries.length }}）</span></summary>
    <ol class="rhist__list">
      <li v-for="e in entries" :key="e.id" class="rhist__entry">
        <p class="rhist__head">
          <strong>{{ e.label }}</strong>
          <span class="num">{{ e.at }}</span>
        </p>
        <p class="rhist__reason">原因：{{ e.reason }}</p>
        <table class="rhist__table">
          <thead>
            <tr>
              <th scope="col">欄位</th>
              <th scope="col">更正前</th>
              <th scope="col">更正後</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in e.rows" :key="r.key" :class="{ 'is-changed': r.changed }">
              <th scope="row">{{ r.label }}</th>
              <td>{{ r.before }}</td>
              <td>{{ r.after }}</td>
            </tr>
          </tbody>
        </table>
      </li>
    </ol>
  </details>
</template>

<style scoped>
.rhist summary {
  cursor: pointer;
  color: var(--ink-dim);
  font-size: 0.8rem;
}
.rhist__list {
  list-style: none;
  margin: 6px 0 0;
  padding: 0;
  display: grid;
  gap: 8px;
}
.rhist__entry {
  padding: 6px 8px;
  border-left: 2px solid var(--accent-2);
  background: color-mix(in srgb, var(--surface-2) 60%, transparent);
}
.rhist__head {
  margin: 0;
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: 0.85rem;
}
.rhist__reason {
  margin: 2px 0 6px;
  font-size: 0.85rem;
  color: var(--ink-dim);
  overflow-wrap: anywhere;
}
.rhist__table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8rem;
}
.rhist__table th,
.rhist__table td {
  padding: 3px 6px;
  text-align: left;
  border-bottom: 1px dashed var(--line);
  overflow-wrap: anywhere;
}
.rhist__table thead th {
  color: var(--ink-faint);
  font-weight: 500;
}
.is-changed td:last-child {
  color: var(--accent);
}
</style>
