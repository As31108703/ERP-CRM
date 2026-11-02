<script setup lang="ts">
import { computed } from "vue";

/** 分段式進度條。`max` 為 0 時視為 0%；`indeterminate` 時不顯示數值。 */
const props = withDefaults(
  defineProps<{
    value?: number;
    max?: number;
    label: string;
    segments?: number;
    tone?: "accent" | "ok" | "warn" | "danger";
    indeterminate?: boolean;
    showValue?: boolean;
  }>(),
  { value: 0, max: 100, segments: 20, tone: "accent", indeterminate: false, showValue: true },
);

const ratio = computed(() => {
  if (props.max <= 0) return 0;
  return Math.min(1, Math.max(0, props.value / props.max));
});
const percent = computed(() => Math.round(ratio.value * 100));
const lit = computed(() => Math.round(ratio.value * props.segments));
</script>

<template>
  <div class="pbar" :class="[`pbar--${tone}`, { 'pbar--indeterminate': indeterminate }]">
    <div class="pbar__head">
      <span class="pbar__label">{{ label }}</span>
      <span v-if="showValue && !indeterminate" class="pbar__value num">{{ percent }}%</span>
    </div>
    <div
      class="pbar__track"
      role="progressbar"
      :aria-label="label"
      aria-valuemin="0"
      :aria-valuemax="indeterminate ? undefined : 100"
      :aria-valuenow="indeterminate ? undefined : percent"
    >
      <span v-for="i in segments" :key="i" class="pbar__seg" :class="{ 'is-lit': !indeterminate && i <= lit }" />
    </div>
  </div>
</template>

<style scoped>
.pbar {
  --tone: var(--accent);
  display: grid;
  gap: 4px;
}
.pbar--ok {
  --tone: var(--ok);
}
.pbar--warn {
  --tone: var(--warn);
}
.pbar--danger {
  --tone: var(--danger);
}
.pbar__head {
  display: flex;
  justify-content: space-between;
  font-size: 0.8rem;
  color: var(--ink-dim);
}
.pbar__value {
  color: var(--tone);
}
.pbar__track {
  display: flex;
  gap: 2px;
  height: 8px;
  padding: 2px;
  border: 1px solid var(--line);
  background: var(--bg-deep);
  clip-path: polygon(4px 0, 100% 0, 100% calc(100% - 4px), calc(100% - 4px) 100%, 0 100%, 0 4px);
}
.pbar__seg {
  flex: 1;
  background: color-mix(in srgb, var(--tone) 12%, transparent);
  transition: background var(--motion-fast);
}
.pbar__seg.is-lit {
  background: var(--tone);
  box-shadow: 0 0 6px var(--tone);
}
.pbar--indeterminate .pbar__seg {
  animation: pbar-sweep 1.4s linear infinite;
}
.pbar--indeterminate .pbar__seg:nth-child(4n + 2) {
  animation-delay: 0.15s;
}
.pbar--indeterminate .pbar__seg:nth-child(4n + 3) {
  animation-delay: 0.3s;
}
.pbar--indeterminate .pbar__seg:nth-child(4n) {
  animation-delay: 0.45s;
}
@keyframes pbar-sweep {
  50% {
    background: var(--tone);
  }
}
@media (prefers-reduced-motion: reduce) {
  .pbar--indeterminate .pbar__seg {
    animation: none;
    background: color-mix(in srgb, var(--tone) 45%, transparent);
  }
}
</style>
