<script setup lang="ts">
/** 訊號燈：以顏色與脈衝表示狀態，文字標籤一定同時顯示（不只靠顏色）。 */
withDefaults(
  defineProps<{ tone?: "ok" | "warn" | "danger" | "info" | "idle"; label: string; pulse?: boolean }>(),
  { tone: "info", pulse: false },
);
</script>

<template>
  <span class="signal" :class="[`signal--${tone}`, { 'signal--pulse': pulse }]">
    <span class="signal__lamp" aria-hidden="true" />
    <span class="signal__label">{{ label }}</span>
  </span>
</template>

<style scoped>
.signal {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 0.8rem;
  letter-spacing: 0.04em;
  white-space: nowrap;
  --lamp: var(--info);
}
.signal--ok {
  --lamp: var(--ok);
}
.signal--warn {
  --lamp: var(--warn);
}
.signal--danger {
  --lamp: var(--danger);
}
.signal--idle {
  --lamp: var(--ink-faint);
}
.signal__lamp {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--lamp);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--lamp) 25%, transparent), 0 0 10px var(--lamp);
}
.signal--idle .signal__lamp {
  box-shadow: none;
}
.signal--pulse .signal__lamp {
  animation: signal-pulse 1.6s ease-in-out infinite;
}
@keyframes signal-pulse {
  50% {
    box-shadow: 0 0 0 5px color-mix(in srgb, var(--lamp) 10%, transparent), 0 0 16px var(--lamp);
  }
}
@media (prefers-reduced-motion: reduce) {
  .signal--pulse .signal__lamp {
    animation: none;
  }
}
</style>
