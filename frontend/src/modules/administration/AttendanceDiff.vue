<script setup lang="ts">
import { formatMinutes, type DiffRow } from "./adminModel";

/** 出勤差異表（A§4）：選定週、組織篩選下每位假員工的排班與手動紀錄淨分鐘。 */
defineProps<{ rows: DiffRow[]; period: string; error?: string }>();
</script>

<template>
  <section class="adiff" aria-label="出勤差異" data-testid="attendance-diff">
    <header class="adiff__head">
      <h3 class="adiff__title">出勤差異</h3>
      <span class="adiff__period num">{{ period }}</span>
    </header>
    <p class="adiff__hint">依各段開始日歸週，差異 = 手動紀錄 − 排班；不受搜尋與紀錄狀態篩選影響，不作薪資依據。</p>
    <p v-if="error" class="adiff__error" role="alert">{{ error }}</p>
    <p v-else-if="rows.length === 0" class="adiff__empty">這週沒有排班或手動出勤。</p>
    <div v-else class="adiff__scroll">
      <table class="adiff__table">
        <thead>
          <tr>
            <th scope="col">假員工</th>
            <th scope="col">排班</th>
            <th scope="col">手動紀錄</th>
            <th scope="col">差異</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in rows" :key="r.staff_id" :data-staff-id="r.staff_id">
            <th scope="row">{{ r.alias }}</th>
            <td class="num">{{ formatMinutes(r.scheduled) }}</td>
            <td class="num">{{ formatMinutes(r.recorded) }}</td>
            <td class="num" :class="{ 'is-neg': r.diff < 0, 'is-pos': r.diff > 0 }">
              {{ r.diff > 0 ? "+" : "" }}{{ formatMinutes(r.diff) }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.adiff {
  padding: var(--pad);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--bg-deep);
}
.adiff__head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
}
.adiff__title {
  margin: 0;
  font-size: 0.95rem;
}
.adiff__period {
  font-size: 0.75rem;
  color: var(--ink-faint);
}
.adiff__hint,
.adiff__empty {
  margin: 4px 0 8px;
  font-size: 0.8rem;
  color: var(--ink-dim);
}
.adiff__error {
  margin: 4px 0;
  color: var(--danger);
}
.adiff__scroll {
  overflow-x: auto;
}
.adiff__table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
}
.adiff__table th,
.adiff__table td {
  padding: 4px 8px;
  text-align: left;
  border-bottom: 1px dashed var(--line);
  white-space: nowrap;
}
.adiff__table thead th {
  color: var(--ink-faint);
  font-weight: 500;
}
.is-neg {
  color: var(--warn);
}
.is-pos {
  color: var(--accent);
}
</style>
