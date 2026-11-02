<script setup lang="ts">
import { computed } from "vue";

/** 指標量表：270° 弧形，數值以等寬字顯示。value／max 為 0 時顯示「—」。 */
const props = withDefaults(
  defineProps<{ value: number; max?: number; label: string; unit?: string; caption?: string }>(),
  { max: 100, unit: "%", caption: "" },
);

const R = 40;
const ARC = 2 * Math.PI * R * 0.75;
const ratio = computed(() => (props.max > 0 ? Math.min(1, Math.max(0, props.value / props.max)) : 0));
const display = computed(() => (props.max > 0 ? String(Math.round(ratio.value * 100)) : "—"));
const tone = computed(() => (ratio.value >= 0.75 ? "ok" : ratio.value >= 0.4 ? "warn" : "danger"));
</script>

<template>
  <figure class="gauge" :class="`gauge--${tone}`">
    <svg viewBox="0 0 100 100" role="img" :aria-label="`${label}：${display}${max > 0 ? unit : ''}`">
      <g transform="rotate(135 50 50)">
        <circle class="gauge__track" cx="50" cy="50" :r="R" :stroke-dasharray="`${ARC} 999`" />
        <circle
          class="gauge__value"
          cx="50"
          cy="50"
          :r="R"
          :stroke-dasharray="`${ARC * ratio} 999`"
        />
      </g>
      <g class="gauge__ticks" aria-hidden="true">
        <line v-for="i in 11" :key="i" x1="50" y1="4" x2="50" y2="8" :transform="`rotate(${-135 + (i - 1) * 27} 50 50)`" />
      </g>
      <text x="50" y="54" class="gauge__num num" text-anchor="middle">{{ display }}</text>
      <text v-if="max > 0" x="50" y="68" class="gauge__unit num" text-anchor="middle">{{ unit }}</text>
    </svg>
    <figcaption>
      <span class="gauge__label">{{ label }}</span>
      <span v-if="caption" class="gauge__caption num">{{ caption }}</span>
    </figcaption>
  </figure>
</template>

<style scoped>
.gauge {
  margin: 0;
  display: grid;
  justify-items: center;
  gap: 4px;
  --tone: var(--accent);
}
.gauge--warn {
  --tone: var(--warn);
}
.gauge--danger {
  --tone: var(--danger);
}
.gauge--ok {
  --tone: var(--ok);
}
svg {
  width: 112px;
  height: 112px;
  overflow: visible;
}
circle {
  fill: none;
  stroke-width: 7;
}
.gauge__track {
  stroke: var(--line);
}
.gauge__value {
  stroke: var(--tone);
  filter: drop-shadow(0 0 4px var(--tone));
  transition: stroke-dasharray var(--motion-slow);
}
.gauge__ticks line {
  stroke: var(--ink-faint);
  stroke-width: 1;
}
.gauge__num {
  fill: var(--ink);
  font-size: 20px;
  font-weight: 600;
}
.gauge__unit {
  fill: var(--ink-faint);
  font-size: 8px;
}
figcaption {
  display: grid;
  justify-items: center;
  font-size: 0.8rem;
}
.gauge__label {
  color: var(--ink-dim);
}
.gauge__caption {
  font-size: 0.72rem;
  color: var(--ink-faint);
}
</style>
