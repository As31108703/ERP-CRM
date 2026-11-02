<script setup lang="ts">
import type { LearningPathId } from "../../api/types";
import { ROUTE_GLYPHS } from "./learning";

/** 路線選擇：每條可用路線一張任務卡，顯示「n／m 步驟已確認」。 */
export interface RouteCard {
  id: LearningPathId;
  title: string;
  subtitle: string;
  confirmed: number;
  total: number;
}

defineProps<{ routes: RouteCard[]; selected: LearningPathId | null; disabled: boolean }>();
defineEmits<{ select: [id: LearningPathId] }>();
</script>

<template>
  <div class="routes" role="group" aria-label="選擇教學路線">
    <button
      v-for="r in routes"
      :key="r.id"
      type="button"
      class="route"
      :class="{ 'is-selected': r.id === selected }"
      :aria-pressed="r.id === selected"
      :disabled="disabled"
      :data-testid="`learning-route-${r.id}`"
      @click="$emit('select', r.id)"
    >
      <span class="route__glyph" aria-hidden="true">{{ ROUTE_GLYPHS[r.id].glyph }}</span>
      <span class="route__body">
        <span class="route__code num" aria-hidden="true">{{ ROUTE_GLYPHS[r.id].code }}</span>
        <strong class="route__title">{{ r.title }}</strong>
        <small class="route__sub">{{ r.subtitle }}</small>
        <span class="route__count num">{{ r.confirmed }}／{{ r.total }} 步驟已確認</span>
      </span>
      <span class="route__meter" aria-hidden="true">
        <span :style="{ width: `${r.total ? (r.confirmed / r.total) * 100 : 0}%` }" />
      </span>
    </button>
  </div>
</template>

<style scoped>
.routes {
  display: grid;
  gap: var(--gap);
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 240px), 1fr));
}
.route {
  position: relative;
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 12px;
  align-items: start;
  text-align: left;
  font: inherit;
  color: var(--ink);
  padding: 12px 14px 16px;
  background: color-mix(in srgb, var(--surface) 82%, transparent);
  border: 1px solid var(--line);
  clip-path: polygon(0 0, calc(100% - var(--cut)) 0, 100% var(--cut), 100% 100%, var(--cut) 100%, 0 calc(100% - var(--cut)));
  cursor: pointer;
  transition: border-color var(--motion-fast), background var(--motion-fast);
}
.route:hover:not(:disabled) {
  border-color: var(--accent);
}
.route:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}
.route.is-selected {
  border-color: var(--accent);
  background: color-mix(in srgb, var(--accent) 12%, var(--surface));
  box-shadow: inset 0 0 18px var(--glow);
}
.route__glyph {
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  font-size: 1.1rem;
  color: var(--accent);
  border: 1px solid var(--accent);
  clip-path: polygon(25% 0, 75% 0, 100% 50%, 75% 100%, 25% 100%, 0 50%);
}
.route__body {
  display: grid;
  gap: 2px;
  min-width: 0;
}
.route__code {
  font-size: 0.66rem;
  letter-spacing: 0.16em;
  color: var(--ink-faint);
}
.route__title {
  font-size: 0.98rem;
}
.route__sub {
  color: var(--ink-dim);
  font-size: 0.8rem;
}
.route__count {
  margin-top: 4px;
  font-size: 0.78rem;
  color: var(--accent);
}
.route__meter {
  position: absolute;
  left: 14px;
  right: 14px;
  bottom: 6px;
  height: 3px;
  background: var(--line);
}
.route__meter span {
  display: block;
  height: 100%;
  background: var(--accent);
  box-shadow: 0 0 6px var(--accent);
}
</style>
