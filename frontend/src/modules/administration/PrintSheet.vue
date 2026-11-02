<script setup lang="ts">
import { tabLabel, type PrintData } from "./adminModel";

/**
 * 列印表（A§6「Print」）：畫面上隱藏，`@media print` 時只印這一張。
 * 內容與匯出的 CSV 相同：12 項範圍說明、聲明、同一組表頭與資料列、筆數與 SIM 聲明。
 */
defineProps<{ data: PrintData | null }>();
</script>

<template>
  <section v-if="data" class="office-print-sheet" data-testid="print-sheet" aria-hidden="true">
    <h1 class="ops__title">SIM 行政紀錄：{{ tabLabel(data.tab) }}</h1>
    <dl class="ops__scope">
      <template v-for="[label, value] in data.scope" :key="label">
        <dt>{{ label }}</dt>
        <dd>{{ value }}</dd>
      </template>
    </dl>
    <p class="ops__disclaimer">本表為 SIM 流程練習資料，人員、組織、時數與金額皆為合成示範，不作薪資、准假、採購或付款依據。</p>
    <table class="ops__table">
      <thead>
        <tr>
          <th v-for="h in data.headers" :key="h" scope="col">{{ h }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(row, i) in data.rows" :key="i">
          <td v-for="(cell, j) in row" :key="j">{{ cell }}</td>
        </tr>
      </tbody>
    </table>
    <p class="ops__footer">共 {{ data.rows.length }} 筆 · SIM 測試資料，不代表任何真實財務或人事紀錄。</p>
  </section>
</template>

<style>
/* 不用 scoped：列印時要隱藏整個應用程式的其他部分。 */
.office-print-sheet {
  display: none;
}
@media print {
  body * {
    visibility: hidden !important;
  }
  .office-print-sheet,
  .office-print-sheet * {
    visibility: visible !important;
  }
  .office-print-sheet {
    display: block;
    position: absolute;
    inset: 0 auto auto 0;
    width: 100%;
    color: #000;
    background: #fff;
    font-size: 10pt;
  }
  .office-print-sheet .ops__title {
    margin: 0 0 8pt;
    font-size: 14pt;
  }
  .office-print-sheet .ops__scope {
    display: grid;
    grid-template-columns: max-content 1fr;
    gap: 2pt 10pt;
    margin: 0 0 8pt;
  }
  .office-print-sheet .ops__scope dt {
    font-weight: 600;
  }
  .office-print-sheet .ops__scope dd {
    margin: 0;
    white-space: pre-wrap;
  }
  .office-print-sheet .ops__table {
    width: 100%;
    border-collapse: collapse;
  }
  .office-print-sheet .ops__table th,
  .office-print-sheet .ops__table td {
    border: 0.5pt solid #555;
    padding: 2pt 4pt;
    text-align: left;
    vertical-align: top;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
  .office-print-sheet .ops__table thead {
    display: table-header-group;
  }
  .office-print-sheet .ops__table tr {
    break-inside: avoid;
  }
}
</style>
