<script setup lang="ts">
import type { LearningPathDef } from "../../api/types";

/** 先想想：答題只用來理解流程，不阻擋實作，也不修改工作區。 */
defineProps<{ quiz: LearningPathDef["quiz"]; pathId: string; choice: number | null; disabled?: boolean }>();
defineEmits<{ choose: [index: number] }>();
</script>

<template>
  <div class="quiz">
    <p class="quiz__kicker num" aria-hidden="true">CHECKPOINT · THINK</p>
    <h2 class="quiz__q">{{ quiz.question }}</h2>
    <fieldset class="quiz__choices">
      <legend class="sr-only">選擇你的答案</legend>
      <label v-for="(text, i) in quiz.choices" :key="text" class="quiz__choice" :class="{ 'is-selected': choice === i }">
        <input
          type="radio"
          :name="`learning-quiz-${pathId}`"
          :checked="choice === i"
          :disabled="disabled"
          :data-testid="`learning-quiz-choice-${i}`"
          @change="$emit('choose', i)"
        />
        <span class="quiz__mark num" aria-hidden="true">{{ String.fromCharCode(65 + i) }}</span>
        <span>{{ text }}</span>
      </label>
    </fieldset>
    <div v-if="choice !== null" class="quiz__answer" role="status" :class="{ 'is-right': choice === quiz.answer }">
      <strong>{{ choice === quiz.answer ? "你抓到這一步的重點了。" : "再看一下資料改變的時機。" }}</strong>
      <p>{{ quiz.explanation }}</p>
    </div>
    <small class="quiz__note">答題只用來理解流程，不會阻擋實作，也不會修改工作區。</small>
  </div>
</template>

<style scoped>
.quiz {
  display: grid;
  gap: 8px;
}
.quiz__kicker {
  margin: 0;
  font-size: 0.68rem;
  letter-spacing: 0.18em;
  color: var(--accent);
}
.quiz__q {
  margin: 0;
  font-size: 1rem;
}
.quiz__choices {
  margin: 0;
  padding: 0;
  border: 0;
  display: grid;
  gap: 6px;
}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}
.quiz__choice {
  display: grid;
  grid-template-columns: auto auto 1fr;
  gap: 8px;
  align-items: center;
  padding: 6px 10px;
  border: 1px solid var(--line);
  cursor: pointer;
  font-size: 0.88rem;
}
.quiz__choice input {
  accent-color: var(--accent);
  min-height: 0;
}
.quiz__choice.is-selected {
  border-color: var(--accent);
  background: color-mix(in srgb, var(--accent) 10%, transparent);
}
.quiz__mark {
  font-size: 0.74rem;
  color: var(--ink-faint);
}
.quiz__answer {
  padding: 8px 10px;
  border-left: 3px solid var(--accent-2);
  background: color-mix(in srgb, var(--accent-2) 8%, transparent);
}
.quiz__answer.is-right {
  border-left-color: var(--accent);
  background: color-mix(in srgb, var(--accent) 8%, transparent);
}
.quiz__answer p {
  margin: 4px 0 0;
  font-size: 0.84rem;
  color: var(--ink-dim);
}
.quiz__note {
  color: var(--ink-faint);
  font-size: 0.74rem;
}
</style>
