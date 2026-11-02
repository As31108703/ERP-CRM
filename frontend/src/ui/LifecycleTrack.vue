<script setup lang="ts">
import { computed } from "vue";
import { lifecycle, TERMINAL_LABELS, type LifecycleKind } from "../lib/lifecycle";

const props = defineProps<{ kind: LifecycleKind; row: Record<string, unknown> | null | undefined }>();

const track = computed(() => lifecycle(props.kind, props.row));
const STATE_LABELS = { done: "已完成", current: "進行中", todo: "未開始", failed: "已中止" } as const;
const summary = computed(() =>
  track.value.stages.map((s) => `${s.label}${STATE_LABELS[s.state]}`).join("、"),
);
</script>

<template>
  <div class="ltrack" :aria-label="`生命週期：${summary}`" role="group">
    <ol class="ltrack__list">
      <li v-for="(stage, i) in track.stages" :key="stage.key" class="ltrack__stage" :class="`is-${stage.state}`">
        <span class="ltrack__bar" aria-hidden="true" />
        <span class="ltrack__label">
          <span class="ltrack__index num" aria-hidden="true">{{ String(i + 1).padStart(2, "0") }}</span>
          {{ stage.label }}
        </span>
      </li>
    </ol>
    <p v-if="track.terminal" class="ltrack__terminal">{{ TERMINAL_LABELS[track.terminal] }}</p>
  </div>
</template>

<style scoped>
.ltrack {
  display: grid;
  gap: 4px;
}
.ltrack__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  gap: 3px;
}
.ltrack__stage {
  flex: 1;
  min-width: 0;
  display: grid;
  gap: 4px;
  --c: var(--line);
}
.ltrack__bar {
  height: 5px;
  background: var(--c);
  clip-path: polygon(0 0, calc(100% - 4px) 0, 100% 50%, calc(100% - 4px) 100%, 0 100%, 4px 50%);
}
.ltrack__stage:first-child .ltrack__bar {
  clip-path: polygon(0 0, calc(100% - 4px) 0, 100% 50%, calc(100% - 4px) 100%, 0 100%);
}
.ltrack__label {
  font-size: 0.72rem;
  color: var(--ink-faint);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ltrack__index {
  font-size: 0.62rem;
  opacity: 0.7;
}
.is-done {
  --c: var(--accent);
}
.is-done .ltrack__label {
  color: var(--ink-dim);
}
.is-current {
  --c: var(--accent-2);
}
.is-current .ltrack__bar {
  box-shadow: 0 0 8px var(--accent-2);
  animation: ltrack-blink 1.8s ease-in-out infinite;
}
.is-current .ltrack__label {
  color: var(--ink);
  font-weight: 600;
}
.is-failed {
  --c: var(--danger);
}
.is-failed .ltrack__label {
  color: var(--danger);
  text-decoration: line-through;
}
.ltrack__terminal {
  margin: 0;
  font-size: 0.72rem;
  color: var(--danger);
}
@keyframes ltrack-blink {
  50% {
    opacity: 0.55;
  }
}
@media (prefers-reduced-motion: reduce) {
  .is-current .ltrack__bar {
    animation: none;
  }
}
</style>
