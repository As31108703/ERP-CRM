<script setup lang="ts">
import { MODULE_ORDER, MODULE_USES, moduleLabel } from "../../lib/modules";

/** 八個模組的勾選清單（建置精靈第 2 步與自訂建置共用）；相依處理由父層 toggle 負責。 */
defineProps<{ modules: string[]; disabled: boolean; dependencies: Readonly<Record<string, readonly string[]>> }>();
const emit = defineEmits<{ toggle: [id: string, on: boolean] }>();

function onChange(id: string, event: Event): void {
  emit("toggle", id, (event.target as HTMLInputElement).checked);
}
</script>

<template>
  <ul class="checklist">
    <li v-for="id in MODULE_ORDER" :key="id" class="checklist__item" :class="{ 'is-on': modules.includes(id) }">
      <label class="checklist__label">
        <input
          type="checkbox"
          :checked="modules.includes(id)"
          :disabled="disabled"
          :data-module="id"
          @change="onChange(id, $event)"
        />
        <span class="checklist__text">
          <strong>{{ moduleLabel(id) }}</strong>
          <small>{{ MODULE_USES[id] }}</small>
          <small v-if="dependencies[id]?.length" class="checklist__deps">
            需要：{{ dependencies[id].map(moduleLabel).join("、") }}
          </small>
        </span>
      </label>
    </li>
  </ul>
</template>

<style scoped>
.checklist {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 8px;
}
.checklist__item {
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  transition: border-color var(--motion-fast);
}
.checklist__item.is-on {
  border-color: var(--accent);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--accent) 30%, transparent);
}
.checklist__label {
  display: flex;
  gap: 10px;
  padding: 10px 12px;
  cursor: pointer;
  align-items: flex-start;
}
.checklist__label input {
  width: auto;
  margin-top: 3px;
  accent-color: var(--accent);
}
.checklist__text {
  display: grid;
  gap: 2px;
  min-width: 0;
}
.checklist__text small {
  color: var(--ink-dim);
  font-size: 0.8rem;
}
.checklist__deps {
  color: var(--ink-faint) !important;
}
</style>
