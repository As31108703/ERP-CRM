<script setup lang="ts">
import type { LearningSnapshot } from "../../api/types";

/** 前後變化看板：這一步執行時的讀值，變動的列會標亮。 */
defineProps<{ snapshot: LearningSnapshot }>();
</script>

<template>
  <section class="board" data-testid="learning-snapshot" aria-label="本次操作前後">
    <header class="board__head">
      <strong>本次操作前後</strong>
      <span class="num">本輪練習 · 操作版本 {{ snapshot.version }}</span>
    </header>
    <table class="board__table">
      <thead>
        <tr>
          <th scope="col">核對項目</th>
          <th scope="col">操作前</th>
          <th scope="col">操作後</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in snapshot.rows" :key="row.label" :class="{ 'is-changed': row.before !== row.after }">
          <th scope="row">{{ row.label }}</th>
          <td class="num">{{ row.before }}</td>
          <td class="num">
            {{ row.after }}
            <span v-if="row.before !== row.after" class="board__delta" aria-label="已變動">Δ</span>
          </td>
        </tr>
      </tbody>
    </table>
    <p class="board__note">本表是操作當時的讀值，完成與否仍以操作收據與目前資料核對。</p>
  </section>
</template>

<style scoped>
.board {
  display: grid;
  gap: 6px;
  padding: 10px 12px;
  border: 1px solid var(--line);
  background: color-mix(in srgb, var(--bg-deep) 60%, transparent);
}
.board__head {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 8px;
  font-size: 0.86rem;
}
.board__head span {
  color: var(--ink-faint);
  font-size: 0.76rem;
}
.board__table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.82rem;
}
.board__table th,
.board__table td {
  text-align: left;
  padding: 4px 6px;
  border-bottom: 1px solid var(--line);
  overflow-wrap: anywhere;
}
.board__table thead th {
  font-weight: 500;
  color: var(--ink-faint);
  font-size: 0.74rem;
}
.board__table tbody th {
  font-weight: 500;
  color: var(--ink-dim);
}
.is-changed td,
.is-changed th {
  color: var(--ink);
  background: color-mix(in srgb, var(--accent) 10%, transparent);
}
.board__delta {
  margin-left: 4px;
  color: var(--accent-2);
  font-weight: 700;
}
.board__note {
  margin: 0;
  font-size: 0.74rem;
  color: var(--ink-faint);
}
</style>
