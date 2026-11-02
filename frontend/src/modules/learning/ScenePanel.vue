<script setup lang="ts">
import { ref } from "vue";
import type { LearningSnapshot, LearningStepDef, LearningStepEval } from "../../api/types";
import ChangeBoard from "./ChangeBoard.vue";

/**
 * 章節場景：標題與說明、「這一步會改變什麼」（預覽或阻擋原因只在目前步驟顯示）、
 * 實際完成證據與檢查點來源，以及前後變化看板。
 */
defineProps<{
  step: LearningStepDef;
  evaluation: LearningStepEval;
  index: number;
  total: number;
  state: string;
  previewText: string | null;
  blockedReason: string | null;
  snapshot: LearningSnapshot | null;
}>();

const heading = ref<HTMLHeadingElement | null>(null);

function focus(smooth: boolean): void {
  heading.value?.focus({ preventScroll: true });
  heading.value?.scrollIntoView?.({ behavior: smooth ? "smooth" : "auto", block: "start" });
}

defineExpose({ focus });
</script>

<template>
  <article class="scene" data-testid="learning-scene">
    <header class="scene__top">
      <span class="scene__no num">章節 {{ String(index + 1).padStart(2, "0") }}／{{ total }}</span>
      <span class="scene__state" :class="{ 'is-complete': evaluation.complete }" data-testid="learning-scene-state">{{ state }}</span>
    </header>
    <h2 ref="heading" class="scene__title" tabindex="-1">{{ step.title }}</h2>
    <p class="scene__body">{{ step.body }}</p>

    <section class="scene__block">
      <h3 class="scene__label">這一步會改變什麼</h3>
      <p>{{ step.change }}</p>
      <p v-if="previewText" class="scene__preview" data-testid="learning-preview">
        <span aria-hidden="true">⟶</span> {{ previewText }}
      </p>
      <p v-if="blockedReason" class="scene__blocked" role="alert" data-testid="learning-blocked">{{ blockedReason }}</p>
    </section>

    <section class="scene__block" data-testid="learning-evidence" aria-live="polite">
      <h3 class="scene__label">實際完成證據</h3>
      <p :class="{ 'scene__evidence': evaluation.complete }">
        {{ evaluation.complete ? evaluation.evidence_text : "尚無本次操作證據。閱讀或觀看示意動畫不會完成這一步。" }}
      </p>
      <details v-if="evaluation.checkpoint" class="scene__source">
        <summary>查看操作來源與紀錄</summary>
        <dl>
          <dt>動作</dt>
          <dd class="num">{{ evaluation.checkpoint.action }}</dd>
          <dt>工作區版本</dt>
          <dd class="num">{{ evaluation.checkpoint.version }}</dd>
          <dt>結果紀錄</dt>
          <dd><code>{{ evaluation.checkpoint.result }}</code></dd>
          <dt>模式</dt>
          <dd>SIM 模擬</dd>
        </dl>
      </details>
    </section>

    <ChangeBoard v-if="snapshot" :snapshot="snapshot" />
    <p v-else-if="evaluation.complete" class="scene__note">這一步沒有保存當時的前後讀值，可用操作紀錄核對完成結果。</p>

    <slot />
  </article>
</template>

<style scoped>
.scene {
  display: grid;
  gap: 10px;
  min-width: 0;
}
.scene__top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}
.scene__no {
  font-size: 0.74rem;
  letter-spacing: 0.14em;
  color: var(--accent);
}
.scene__state {
  font-size: 0.74rem;
  padding: 1px 10px;
  border: 1px solid var(--accent-2);
  color: var(--accent-2);
  clip-path: polygon(6px 0, 100% 0, calc(100% - 6px) 100%, 0 100%);
}
.scene__state.is-complete {
  border-color: var(--accent);
  color: var(--accent);
}
.scene__title {
  margin: 0;
  font-family: var(--font-display);
  font-size: 1.3rem;
  outline: none;
  scroll-margin-top: calc(var(--bar-height) + 12px);
}
.scene__body {
  margin: 0;
  color: var(--ink-dim);
}
.scene__block {
  display: grid;
  gap: 4px;
  padding: 8px 12px;
  border-left: 2px solid var(--line-strong);
  background: color-mix(in srgb, var(--surface-2) 50%, transparent);
}
.scene__block p {
  margin: 0;
}
.scene__label {
  margin: 0;
  font-size: 0.74rem;
  font-weight: 500;
  letter-spacing: 0.1em;
  color: var(--ink-faint);
}
.scene__preview {
  color: var(--accent);
}
.scene__blocked {
  color: var(--accent-2);
}
.scene__evidence {
  color: var(--ink);
}
.scene__source summary {
  cursor: pointer;
  font-size: 0.8rem;
  color: var(--ink-dim);
}
.scene__source dl {
  margin: 6px 0 0;
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 2px 12px;
  font-size: 0.8rem;
}
.scene__source dt {
  color: var(--ink-faint);
}
.scene__source dd {
  margin: 0;
  overflow-wrap: anywhere;
}
.scene__note {
  margin: 0;
  font-size: 0.8rem;
  color: var(--ink-faint);
}
</style>
