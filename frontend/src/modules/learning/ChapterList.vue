<script setup lang="ts">
import type { LearningStepDef, LearningStepEval } from "../../api/types";

/** 章節側欄：點選只開啟閱讀，不寫入工作區資料。 */
defineProps<{
  steps: LearningStepDef[];
  evaluation: LearningStepEval[];
  current: number;
  next: number;
  disabled: boolean;
}>();
defineEmits<{ select: [id: string] }>();
</script>

<template>
  <aside class="chapters">
    <p class="chapters__head">
      <span>章節</span>
      <span class="chapters__hint">任選閱讀</span>
    </p>
    <nav aria-label="教學章節">
      <ol class="chapters__list">
        <li v-for="(step, i) in steps" :key="step.id">
          <button
            type="button"
            class="chapter"
            :class="{ 'is-current': i === current, 'is-complete': evaluation[i]?.complete, 'is-next': i === next }"
            :aria-current="i === current ? 'step' : undefined"
            :disabled="disabled"
            :data-testid="`learning-step-${step.id}`"
            @click="$emit('select', step.id)"
          >
            <span class="chapter__no num" aria-hidden="true">{{ evaluation[i]?.complete ? "✓" : String(i + 1).padStart(2, "0") }}</span>
            <span class="chapter__text">
              <strong>{{ step.title }}</strong>
              <small>{{ evaluation[i]?.complete ? "已確認操作證據" : i === next ? "下一個實作步驟" : "閱讀預覽" }}</small>
            </span>
          </button>
        </li>
      </ol>
    </nav>
    <p class="chapters__note">切換章節只供閱讀，不會寫入資料，也不會算成完成。</p>
  </aside>
</template>

<style scoped>
.chapters {
  display: grid;
  gap: 8px;
  align-content: start;
}
.chapters__head {
  margin: 0;
  display: flex;
  justify-content: space-between;
  font-family: var(--font-mono);
  font-size: 0.74rem;
  letter-spacing: 0.14em;
  color: var(--accent);
}
.chapters__hint {
  color: var(--ink-faint);
  letter-spacing: 0.04em;
}
.chapters__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 4px;
  border-left: 1px dashed var(--line-strong);
}
.chapter {
  width: 100%;
  display: grid;
  grid-template-columns: 30px 1fr;
  gap: 8px;
  align-items: center;
  text-align: left;
  font: inherit;
  color: var(--ink-dim);
  background: transparent;
  border: 0;
  border-left: 2px solid transparent;
  margin-left: -1px;
  padding: 6px 8px;
  cursor: pointer;
}
.chapter:hover:not(:disabled) {
  color: var(--ink);
  background: color-mix(in srgb, var(--accent) 8%, transparent);
}
.chapter:disabled {
  cursor: not-allowed;
}
.chapter.is-current {
  color: var(--ink);
  border-left-color: var(--accent);
  background: color-mix(in srgb, var(--accent) 14%, transparent);
}
.chapter__no {
  font-size: 0.78rem;
  color: var(--ink-faint);
}
.chapter.is-complete .chapter__no {
  color: var(--ok, var(--accent));
}
.chapter.is-next .chapter__no {
  color: var(--accent-2);
}
.chapter__text {
  display: grid;
  min-width: 0;
}
.chapter__text strong {
  font-size: 0.88rem;
  font-weight: 600;
}
.chapter__text small {
  font-size: 0.72rem;
  color: var(--ink-faint);
}
.chapters__note {
  margin: 0;
  font-size: 0.74rem;
  color: var(--ink-faint);
}
</style>
