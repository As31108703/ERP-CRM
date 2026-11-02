<script setup lang="ts">
import { nextTick, ref } from "vue";
import { ADMIN_TABS, type AdminTab } from "./adminModel";

/**
 * 行政分頁列（WAI-ARIA tabs）：每個分頁顯示筆數；←／→ 循環切換，Home／End 到第一個／最後一個，
 * 切換時焦點跟著移動（roving tabindex）。
 */
const props = defineProps<{ modelValue: AdminTab; counts: Partial<Record<AdminTab, number>>; idPrefix: string }>();
const emit = defineEmits<{ "update:modelValue": [tab: AdminTab] }>();

const list = ref<HTMLElement | null>(null);

async function select(index: number): Promise<void> {
  const tab = ADMIN_TABS[(index + ADMIN_TABS.length) % ADMIN_TABS.length].id;
  emit("update:modelValue", tab);
  await nextTick();
  list.value?.querySelector<HTMLElement>(`[data-tab="${tab}"]`)?.focus();
}

function onKey(event: KeyboardEvent): void {
  const current = ADMIN_TABS.findIndex((t) => t.id === props.modelValue);
  const moves: Record<string, number> = {
    ArrowRight: current + 1,
    ArrowLeft: current - 1,
    Home: 0,
    End: ADMIN_TABS.length - 1,
  };
  if (!(event.key in moves)) return;
  event.preventDefault();
  void select(moves[event.key]);
}
</script>

<template>
  <div ref="list" class="atabs" role="tablist" aria-label="行政資料類型" data-testid="admin-tabs" @keydown="onKey">
    <button
      v-for="t in ADMIN_TABS"
      :id="`${idPrefix}-tab-${t.id}`"
      :key="t.id"
      type="button"
      role="tab"
      class="atabs__tab"
      :data-tab="t.id"
      :aria-selected="modelValue === t.id ? 'true' : 'false'"
      :aria-controls="`${idPrefix}-panel`"
      :tabindex="modelValue === t.id ? 0 : -1"
      @click="emit('update:modelValue', t.id)"
    >
      <span>{{ t.label }}</span>
      <span class="atabs__count num">{{ counts[t.id] ?? 0 }}</span>
    </button>
  </div>
</template>

<style scoped>
.atabs {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  border-bottom: 1px solid var(--line);
}
.atabs__tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  background: transparent;
  border: 1px solid transparent;
  border-bottom: 2px solid transparent;
  color: var(--ink-dim);
  font: inherit;
  cursor: pointer;
  transition: color var(--motion-fast), border-color var(--motion-fast);
}
.atabs__tab:hover {
  color: var(--ink);
}
.atabs__tab[aria-selected="true"] {
  color: var(--accent);
  border-bottom-color: var(--accent);
  background: color-mix(in srgb, var(--accent) 8%, transparent);
}
.atabs__tab:focus-visible {
  outline: 1px solid var(--accent);
  outline-offset: -2px;
}
.atabs__count {
  min-width: 1.6em;
  padding: 0 4px;
  font-size: 0.72rem;
  text-align: center;
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-sm);
}
</style>
