<script setup lang="ts">
import type { Template } from "../../api/types";
import { INDUSTRY_HINTS } from "./useBuilder";

/** 產業範本卡片（建置精靈第 1 步與自訂建置共用）。選擇後由父層重設模組。 */
defineProps<{ templates: Template[]; selected: string; disabled: boolean }>();
const emit = defineEmits<{ choose: [id: string] }>();
</script>

<template>
  <div class="tpl-grid" role="group" aria-label="產業範本">
    <button
      v-for="t in templates"
      :key="t.id"
      type="button"
      class="tpl"
      :class="{ 'is-selected': selected === t.id }"
      :aria-pressed="selected === t.id"
      :disabled="disabled"
      :data-industry="t.id"
      @click="emit('choose', t.id)"
    >
      <span class="tpl__glyph" aria-hidden="true">{{ INDUSTRY_HINTS[t.id]?.glyph ?? "◇" }}</span>
      <strong class="tpl__name">{{ t.name }}</strong>
      <small class="tpl__examples">{{ INDUSTRY_HINTS[t.id]?.examples ?? t.purpose }}</small>
      <small class="tpl__count num">{{ t.modules.length }} 個模組</small>
    </button>
  </div>
</template>

<style scoped>
.tpl-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
  gap: 8px;
}
.tpl {
  display: grid;
  gap: 4px;
  justify-items: start;
  text-align: left;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  color: var(--ink);
  font: inherit;
  cursor: pointer;
  transition: border-color var(--motion-fast), background var(--motion-fast);
}
.tpl:hover:not(:disabled) {
  border-color: var(--line-strong);
}
.tpl:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.tpl.is-selected {
  border-color: var(--accent);
  background: color-mix(in srgb, var(--accent) 12%, var(--surface-2));
  box-shadow: 0 0 12px var(--glow);
}
.tpl__glyph {
  font-size: 1.2rem;
  color: var(--accent);
}
.tpl__examples {
  color: var(--ink-dim);
  font-size: 0.8rem;
}
.tpl__count {
  color: var(--ink-faint);
  font-size: 0.72rem;
}
</style>
