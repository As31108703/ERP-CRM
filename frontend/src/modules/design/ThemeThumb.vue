<script setup lang="ts">
import { computed } from "vue";
import type { ThemeDef } from "../../themes/themes";

/** 主題縮圖：以該主題的色票畫一個迷你工作台（導覽軌、指令列、面板、量表）。 */
const props = defineProps<{ theme: ThemeDef }>();

const c = computed(() => {
  const [bg, surface, ink, accent, accent2] = props.theme.palette;
  return { bg, surface, ink, accent, accent2 };
});
const uid = computed(() => `thumb-${props.theme.id}`);

function panel(x: number, y: number, w: number, h: number): string {
  if (props.theme.panelStyle === "notched") {
    const k = 6;
    return `M${x + k} ${y}H${x + w}V${y + h - k}L${x + w - k} ${y + h}H${x}V${y + k}Z`;
  }
  const r = props.theme.panelStyle === "rounded" ? 7 : 1.5;
  return `M${x + r} ${y}H${x + w - r}Q${x + w} ${y} ${x + w} ${y + r}V${y + h - r}Q${x + w} ${y + h} ${x + w - r} ${y + h}H${x + r}Q${x} ${y + h} ${x} ${y + h - r}V${y + r}Q${x} ${y} ${x + r} ${y}Z`;
}
const panels = [
  [44, 26, 70, 46],
  [120, 26, 74, 46],
  [44, 78, 150, 34],
] as const;
</script>

<template>
  <svg class="thumb" viewBox="0 0 200 120" role="img" :aria-label="`${theme.name} 縮圖`">
    <defs>
      <pattern :id="`${uid}-grid`" width="10" height="10" patternUnits="userSpaceOnUse">
        <path d="M10 0H0V10" fill="none" :stroke="c.accent" stroke-opacity="0.08" stroke-width="0.6" />
      </pattern>
      <radialGradient :id="`${uid}-neb`" cx="0.85" cy="0" r="0.8">
        <stop offset="0" :stop-color="c.accent" stop-opacity="0.25" />
        <stop offset="1" :stop-color="c.accent" stop-opacity="0" />
      </radialGradient>
    </defs>
    <rect width="200" height="120" :fill="c.bg" />
    <rect width="200" height="120" :fill="`url(#${uid}-grid)`" />
    <rect width="200" height="120" :fill="`url(#${uid}-neb)`" />
    <circle v-for="(s, i) in [[18, 100], [70, 12], [150, 116], [192, 60], [104, 74]]" :key="i" :cx="s[0]" :cy="s[1]" r="0.8" :fill="c.ink" opacity="0.7" />
    <!-- 指令列 -->
    <rect x="0" y="0" width="200" height="16" :fill="c.surface" opacity="0.9" />
    <rect x="0" y="15.5" width="200" height="0.8" :fill="c.accent" opacity="0.7" />
    <circle cx="9" cy="8" r="3" :fill="c.accent" />
    <rect x="16" y="6" width="22" height="4" rx="1" :fill="c.ink" opacity="0.85" />
    <rect x="168" y="5" width="26" height="6" :fill="c.accent" />
    <!-- 導覽軌 -->
    <rect x="0" y="16" width="36" height="104" :fill="c.surface" opacity="0.75" />
    <rect v-for="i in 6" :key="`r${i}`" x="6" :y="22 + i * 12" :width="i === 2 ? 26 : 22" height="4" rx="1" :fill="i === 2 ? c.accent : c.ink" :opacity="i === 2 ? 1 : 0.35" />
    <!-- 面板 -->
    <path v-for="(p, i) in panels" :key="`p${i}`" :d="panel(p[0], p[1], p[2], p[3])" :fill="c.surface" :stroke="i === 0 ? c.accent : c.accent2" stroke-opacity="0.75" stroke-width="0.9" />
    <template v-if="theme.panelStyle === 'bracket'">
      <path v-for="(p, i) in panels" :key="`b${i}`" :d="`M${p[0] + 2} ${p[1] + 8}V${p[1] + 2}H${p[0] + 8}`" fill="none" :stroke="c.accent" stroke-width="1.6" />
    </template>
    <!-- 量表 -->
    <circle cx="66" cy="52" r="11" fill="none" :stroke="c.ink" stroke-opacity="0.15" stroke-width="3" />
    <circle cx="66" cy="52" r="11" fill="none" :stroke="c.accent" stroke-width="3" stroke-dasharray="48 100" transform="rotate(135 66 52)" />
    <rect x="84" y="44" width="24" height="3" :fill="c.ink" opacity="0.6" />
    <rect x="84" y="51" width="18" height="3" :fill="c.ink" opacity="0.3" />
    <!-- 長條 -->
    <rect v-for="i in 5" :key="`g${i}`" :x="128 + (i - 1) * 13" :y="64 - i * 5 - 4" width="8" :height="i * 5 + 4" :fill="i === 4 ? c.accent2 : c.accent" :opacity="i === 4 ? 1 : 0.55" />
    <!-- 生命週期軌道 -->
    <rect v-for="i in 4" :key="`t${i}`" :x="52 + (i - 1) * 35" y="92" width="32" height="4" :fill="i < 3 ? c.accent : i === 3 ? c.accent2 : c.ink" :opacity="i === 4 ? 0.2 : 1" />
    <rect x="52" y="101" width="60" height="3" :fill="c.ink" opacity="0.35" />
  </svg>
</template>

<style scoped>
.thumb {
  display: block;
  width: 100%;
  height: auto;
  aspect-ratio: 5 / 3;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
}
</style>
