<script setup lang="ts">
withDefaults(defineProps<{ title: string; text?: string }>(), { text: "" });
</script>

<template>
  <div class="empty" role="status">
    <svg class="empty__glyph" viewBox="0 0 48 48" aria-hidden="true">
      <circle cx="24" cy="24" r="20" />
      <circle cx="24" cy="24" r="11" />
      <circle cx="40" cy="15" r="2.5" class="empty__sat" />
    </svg>
    <p class="empty__title">{{ title }}</p>
    <p v-if="text" class="empty__text">{{ text }}</p>
    <div v-if="$slots.default" class="empty__actions"><slot /></div>
  </div>
</template>

<style scoped>
.empty {
  display: grid;
  justify-items: center;
  text-align: center;
  gap: 6px;
  padding: calc(var(--pad) * 1.5) var(--pad);
  border: 1px dashed var(--line);
  border-radius: var(--radius-sm);
  color: var(--ink-dim);
}
.empty__glyph {
  width: 44px;
  height: 44px;
  fill: none;
  stroke: var(--line-strong);
  stroke-dasharray: 3 4;
}
.empty__sat {
  fill: var(--accent);
  stroke: none;
}
.empty__title {
  margin: 0;
  color: var(--ink);
  font-weight: 600;
}
.empty__text {
  margin: 0;
  font-size: 0.9rem;
}
.empty__actions {
  margin-top: 6px;
  display: flex;
  gap: 8px;
}
</style>
