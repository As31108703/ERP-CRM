<script setup lang="ts">
/** 模組頁標題列：裝飾用 HUD 代碼、標題、說明與頁面層級的操作按鈕。 */
defineProps<{ code: string; title: string; lead: string }>();
</script>

<template>
  <header class="phead">
    <div class="phead__text">
      <p class="phead__code num" aria-hidden="true">{{ code }}</p>
      <h1 class="phead__title">{{ title }}</h1>
      <p class="phead__lead">{{ lead }}</p>
    </div>
    <div v-if="$slots.default" class="phead__actions"><slot /></div>
  </header>
</template>

<style scoped>
.phead {
  display: flex;
  flex-wrap: wrap;
  gap: var(--gap);
  align-items: flex-end;
  justify-content: space-between;
  margin-bottom: var(--gap);
}
.phead__text {
  flex: 1 1 320px;
  min-width: 0;
}
.phead__code {
  margin: 0;
  font-size: 0.72rem;
  letter-spacing: 0.18em;
  color: var(--accent);
}
.phead__title {
  margin: 2px 0 4px;
  font-family: var(--font-display);
  font-size: 1.6rem;
  letter-spacing: 0.04em;
}
.phead__lead {
  margin: 0;
  color: var(--ink-dim);
  max-width: 64ch;
}
.phead__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: flex-start;
}
.phead__actions :deep(.phead__reason) {
  align-self: center;
  font-size: 0.8rem;
  color: var(--ink-faint);
}
</style>
