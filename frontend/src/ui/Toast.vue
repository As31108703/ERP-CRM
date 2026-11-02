<script setup lang="ts">
/** 頂部通知列：成功、錯誤、待確認。文字一定可讀，不只靠顏色。 */
withDefaults(defineProps<{ tone?: "ok" | "danger" | "warn" | "info"; title?: string; dismissible?: boolean }>(), {
  tone: "info",
  title: "",
  dismissible: false,
});
defineEmits<{ dismiss: [] }>();
</script>

<template>
  <div class="toast" :class="`toast--${tone}`" :role="tone === 'danger' || tone === 'warn' ? 'alert' : 'status'">
    <span class="toast__lamp" aria-hidden="true" />
    <strong v-if="title" class="toast__title">{{ title }}</strong>
    <span class="toast__body"><slot /></span>
    <span v-if="$slots.actions" class="toast__actions"><slot name="actions" /></span>
    <button v-if="dismissible" type="button" class="toast__close" aria-label="關閉訊息" @click="$emit('dismiss')">×</button>
  </div>
</template>

<style scoped>
.toast {
  --tone: var(--info);
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
  padding: 8px 12px;
  border: 1px solid color-mix(in srgb, var(--tone) 60%, transparent);
  border-left: 3px solid var(--tone);
  background: color-mix(in srgb, var(--tone) 9%, var(--surface));
  color: var(--ink);
  clip-path: polygon(0 0, calc(100% - 10px) 0, 100% 10px, 100% 100%, 0 100%);
  animation: toast-in var(--motion-base) ease-out;
}
.toast--ok {
  --tone: var(--ok);
}
.toast--danger {
  --tone: var(--danger);
}
.toast--warn {
  --tone: var(--warn);
}
.toast__lamp {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--tone);
  box-shadow: 0 0 8px var(--tone);
}
.toast__title {
  color: var(--tone);
}
.toast__body {
  flex: 1 1 200px;
}
.toast__actions {
  display: flex;
  gap: 8px;
}
.toast__close {
  background: none;
  border: 0;
  color: var(--ink-dim);
  font-size: 1.2rem;
  cursor: pointer;
  line-height: 1;
}
.toast__close:hover {
  color: var(--ink);
}
@keyframes toast-in {
  from {
    opacity: 0;
    transform: translateY(-4px);
  }
}
@media (prefers-reduced-motion: reduce) {
  .toast {
    animation: none;
  }
}
</style>
