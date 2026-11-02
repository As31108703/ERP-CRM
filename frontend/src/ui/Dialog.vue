<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from "vue";

/**
 * 模態對話框。開啟時帶 `data-erpcrm-dialog` 標記，全域快捷鍵（Esc 取消試看、Ctrl K）會因此讓路。
 * 焦點：開啟時移到第一個可聚焦元素，Tab 在框內循環，關閉後還給開啟前的元素。
 */
const props = withDefaults(defineProps<{ open: boolean; title: string; code?: string; wide?: boolean }>(), {
  code: "",
  wide: false,
});
const emit = defineEmits<{ close: [] }>();

const box = ref<HTMLElement | null>(null);
const titleId = `dlg-${Math.random().toString(36).slice(2, 8)}`;
let restore: HTMLElement | null = null;

const FOCUSABLE = "button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])";

function focusables(): HTMLElement[] {
  return box.value ? Array.from(box.value.querySelectorAll<HTMLElement>(FOCUSABLE)) : [];
}

watch(
  () => props.open,
  async (open) => {
    if (open) {
      restore = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      await nextTick();
      (focusables()[0] ?? box.value)?.focus();
    } else if (restore) {
      restore.focus();
      restore = null;
    }
  },
  { immediate: true },
);

onBeforeUnmount(() => restore?.focus());

function onKey(event: KeyboardEvent): void {
  if (event.key === "Escape") {
    event.preventDefault();
    emit("close");
    return;
  }
  if (event.key !== "Tab") return;
  const list = focusables();
  if (!list.length) return;
  const first = list[0];
  const last = list[list.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="dlg-backdrop" data-erpcrm-dialog @mousedown.self="emit('close')">
      <div
        ref="box"
        class="dlg"
        :class="{ 'dlg--wide': wide }"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="titleId"
        tabindex="-1"
        @keydown="onKey"
      >
        <header class="dlg__head">
          <h2 :id="titleId" class="dlg__title">{{ title }}</h2>
          <span v-if="code" class="dlg__code num" aria-hidden="true">{{ code }}</span>
          <button type="button" class="dlg__close" aria-label="關閉" @click="emit('close')">×</button>
        </header>
        <div class="dlg__body"><slot /></div>
        <footer v-if="$slots.footer" class="dlg__foot"><slot name="footer" /></footer>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.dlg-backdrop {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: grid;
  place-items: center;
  padding: 16px;
  background: color-mix(in srgb, var(--bg-deep) 78%, transparent);
  backdrop-filter: blur(3px);
  animation: dlg-fade var(--motion-base) ease-out;
}
.dlg {
  width: min(520px, 100%);
  max-height: calc(100dvh - 32px);
  display: flex;
  flex-direction: column;
  background: var(--surface);
  border: 1px solid var(--accent);
  box-shadow: 0 0 0 1px var(--line), 0 0 32px var(--glow);
  clip-path: var(--panel-clip);
  border-radius: var(--panel-radius);
  outline: none;
}
.dlg--wide {
  width: min(820px, 100%);
}
.dlg__head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: var(--pad);
  border-bottom: 1px dashed var(--line);
}
.dlg__title {
  margin: 0;
  flex: 1;
  font-family: var(--font-display);
  font-size: 1.05rem;
  letter-spacing: 0.04em;
}
.dlg__code {
  font-size: 0.7rem;
  color: var(--ink-faint);
}
.dlg__close {
  background: none;
  border: 0;
  color: var(--ink-dim);
  font-size: 1.3rem;
  cursor: pointer;
}
.dlg__body {
  padding: var(--pad);
  overflow: auto;
}
.dlg__foot {
  display: flex;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 8px;
  padding: var(--pad);
  border-top: 1px dashed var(--line);
}
@keyframes dlg-fade {
  from {
    opacity: 0;
  }
}
@media (prefers-reduced-motion: reduce) {
  .dlg-backdrop {
    animation: none;
  }
}
</style>
