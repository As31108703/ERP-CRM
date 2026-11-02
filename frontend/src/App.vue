<script setup lang="ts">
import { computed } from "vue";
import { RouterView } from "vue-router";
import { pendingStorageVolatile } from "./api/pending";
import { useWorkspaceStore } from "./stores/workspace";
import AppShell from "./ui/AppShell.vue";
import Toast from "./ui/Toast.vue";

const store = useWorkspaceStore();
const volatile = computed(() => store.pending !== null && pendingStorageVolatile());
</script>

<template>
  <AppShell>
    <template #notices>
      <template v-if="store.loaded">
        <Toast v-if="store.error" tone="danger" title="操作尚未完成">
          {{ store.error }}
          <template #actions>
            <button type="button" class="btn btn--sm" :disabled="store.busy" @click="store.refresh()">重新讀取</button>
          </template>
        </Toast>
        <Toast v-if="store.message" tone="ok" dismissible @dismiss="store.dismissMessage()">{{ store.message }}</Toast>
        <Toast v-if="store.pending" tone="warn" title="上次操作的結果尚未確認" data-testid="pending-notice">
          <span v-if="volatile">瀏覽器儲存目前無法使用，重新整理頁面後將無法確認這筆操作。</span>
          <template #actions>
            <button type="button" class="btn btn--sm" :disabled="store.busy" @click="store.retry()">確認原操作結果</button>
          </template>
        </Toast>
      </template>
    </template>
    <p v-if="!store.loaded" class="app-loading">
      <span class="app-loading__orbit" aria-hidden="true" />
      準備你的測試工作區
    </p>
    <RouterView v-else />
  </AppShell>
</template>

<style scoped>
.app-loading {
  display: flex;
  align-items: center;
  gap: 12px;
  color: var(--ink-dim);
  font-family: var(--font-display);
  letter-spacing: 0.08em;
}
.app-loading__orbit {
  width: 18px;
  height: 18px;
  border: 2px solid var(--line-strong);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: app-spin 0.9s linear infinite;
}
@keyframes app-spin {
  to {
    transform: rotate(360deg);
  }
}
@media (prefers-reduced-motion: reduce) {
  .app-loading__orbit {
    animation: none;
  }
}
</style>
