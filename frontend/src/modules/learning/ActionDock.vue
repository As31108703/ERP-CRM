<script setup lang="ts">
/**
 * 操作列：「執行這一步」永遠顯示，條件不符時停用；回看已完成步驟可前往下一個實作步驟，
 * 預讀後面的步驟可回到目前實作步驟。寬度 760px 以下固定在畫面底部。
 */
defineProps<{
  hasSession: boolean;
  canExecute: boolean;
  readingPast: boolean;
  readingAhead: boolean;
  complete: boolean;
  paused: boolean;
  pending: boolean;
  busy: boolean;
  disabled: boolean;
}>();
defineEmits<{ execute: []; start: []; next: []; back: []; inspect: [] }>();
</script>

<template>
  <div class="dock" data-testid="learning-action-dock">
    <p class="dock__hint">
      <template v-if="!hasSession">先開始這條路線，才會建立本輪練習。</template>
      <template v-else-if="readingPast">這一步已有證據，回看不會重複執行。</template>
      <template v-else-if="readingAhead">先完成前面的實作，再回到這一步。</template>
      <template v-else-if="paused">繼續教學後，就能執行這一步。</template>
      <template v-else-if="pending">先確認上次操作的結果，再繼續實作。</template>
      <template v-else>按下按鈕才會執行上方預覽的模擬操作。</template>
    </p>
    <div class="dock__buttons">
      <button v-if="!hasSession" type="button" class="btn btn--primary" data-testid="learning-start" :disabled="disabled" @click="$emit('start')">
        開始這條路線
      </button>
      <button
        v-if="readingPast && !complete"
        type="button"
        class="btn"
        data-testid="learning-next"
        :disabled="disabled"
        @click="$emit('next')"
      >
        前往下一個實作步驟
      </button>
      <button v-if="readingAhead" type="button" class="btn" data-testid="learning-back-to-current" :disabled="disabled" @click="$emit('back')">
        回到目前實作步驟
      </button>
      <button
        type="button"
        class="btn btn--primary dock__exec"
        data-testid="learning-execute"
        :disabled="!canExecute"
        @click="canExecute && $emit('execute')"
      >
        {{ busy ? "等待操作確認…" : "執行這一步" }}
      </button>
      <button type="button" class="btn btn--ghost" data-testid="learning-inspect" @click="$emit('inspect')">到工作台核對 ↗</button>
    </div>
  </div>
</template>

<style scoped>
.dock {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  border: 1px solid var(--line-strong);
  background: color-mix(in srgb, var(--bg-deep) 85%, transparent);
}
.dock__hint {
  margin: 0;
  flex: 1 1 220px;
  font-size: 0.82rem;
  color: var(--ink-dim);
}
.dock__buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
@media (max-width: 760px) {
  .dock {
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 30;
    border-width: 1px 0 0;
    padding: 8px 12px calc(8px + env(safe-area-inset-bottom));
    backdrop-filter: blur(8px);
  }
  .dock__hint {
    flex-basis: 100%;
    font-size: 0.76rem;
  }
  .dock__buttons {
    width: 100%;
  }
  .dock__exec {
    flex: 1;
  }
}
</style>
