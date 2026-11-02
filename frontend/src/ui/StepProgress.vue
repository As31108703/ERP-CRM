<script setup lang="ts">
import { computed } from "vue";

/** 步驟進度（建置精靈、教學路線、備份流程）。`current` 為目前步驟索引；`failedAt` 標出失敗步驟。 */
const props = withDefaults(
  defineProps<{ steps: string[]; current: number; label: string; failedAt?: number | null }>(),
  { failedAt: null },
);

function stateOf(i: number): "done" | "current" | "todo" | "failed" {
  if (props.failedAt === i) return "failed";
  if (i < props.current) return "done";
  if (i === props.current) return "current";
  return "todo";
}
const doneCount = computed(() => Math.min(props.steps.length, Math.max(0, props.current)));
</script>

<template>
  <nav class="steps" :aria-label="label">
    <p class="steps__meta">
      <span>{{ label }}</span>
      <span class="num">{{ doneCount }}／{{ steps.length }}</span>
    </p>
    <ol class="steps__list">
      <li
        v-for="(step, i) in steps"
        :key="step"
        class="steps__item"
        :class="`is-${stateOf(i)}`"
        :aria-current="stateOf(i) === 'current' ? 'step' : undefined"
      >
        <span class="steps__node num" aria-hidden="true">{{ stateOf(i) === "done" ? "✓" : stateOf(i) === "failed" ? "!" : i + 1 }}</span>
        <span class="steps__text">{{ step }}</span>
      </li>
    </ol>
  </nav>
</template>

<style scoped>
.steps__meta {
  margin: 0 0 6px;
  display: flex;
  justify-content: space-between;
  font-size: 0.8rem;
  color: var(--ink-dim);
}
.steps__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  gap: 0;
}
.steps__item {
  flex: 1;
  min-width: 0;
  display: grid;
  justify-items: center;
  gap: 4px;
  position: relative;
  --c: var(--line-strong);
}
.steps__item:not(:first-child)::before {
  content: "";
  position: absolute;
  top: 11px;
  right: calc(50% + 14px);
  left: calc(-50% + 14px);
  height: 2px;
  background: var(--c);
}
.steps__node {
  width: 24px;
  height: 24px;
  display: grid;
  place-items: center;
  font-size: 0.72rem;
  border: 1px solid var(--c);
  color: var(--c);
  background: var(--bg-deep);
  clip-path: polygon(50% 0, 100% 50%, 50% 100%, 0 50%);
}
.steps__text {
  font-size: 0.75rem;
  color: var(--ink-faint);
  text-align: center;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}
.is-done {
  --c: var(--accent);
}
.is-done .steps__node {
  background: var(--accent);
  color: var(--accent-ink);
}
.is-current {
  --c: var(--accent-2);
}
.is-current .steps__node {
  box-shadow: inset 0 0 8px var(--accent-2);
}
.is-current .steps__text {
  color: var(--ink);
  font-weight: 600;
}
.is-failed {
  --c: var(--danger);
}
.is-failed .steps__text {
  color: var(--danger);
}
</style>
