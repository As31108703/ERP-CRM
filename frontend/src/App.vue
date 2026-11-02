<script setup lang="ts">
import { computed } from "vue";
import { RouterView } from "vue-router";
import { inflight } from "./api/client";
import { pendingStorageVolatile } from "./api/pending";
import { useWorkspaceStore } from "./stores/workspace";

const store = useWorkspaceStore();
const loading = computed(() => inflight.value > 0);
const volatile = computed(() => store.pending !== null && pendingStorageVolatile());
</script>

<template>
  <div class="app" :class="store.hasWorkspace ? 'app-layout' : 'welcome-layout'">
    <div v-if="loading" class="global-loading" role="progressbar" aria-label="讀取中" data-testid="global-loading" />
    <main>
      <p v-if="!store.loaded" class="loading">準備你的測試工作區</p>
      <template v-else>
        <div v-if="store.error" class="notice notice-error" role="alert">
          <strong>操作尚未完成</strong>
          <span>{{ store.error }}</span>
          <button type="button" :disabled="store.busy" @click="store.refresh()">重新讀取</button>
        </div>
        <div v-if="store.message" class="notice notice-ok" role="status">
          <span>{{ store.message }}</span>
          <button type="button" aria-label="關閉訊息" @click="store.dismissMessage()">×</button>
        </div>
        <div v-if="store.pending" class="notice notice-pending" role="alert" data-testid="pending-notice">
          <strong>上次操作的結果尚未確認</strong>
          <button type="button" :disabled="store.busy" @click="store.retry()">確認原操作結果</button>
          <span v-if="volatile">瀏覽器儲存目前無法使用，重新整理頁面後將無法確認這筆操作。</span>
        </div>
      </template>
      <RouterView v-if="store.loaded" />
    </main>
  </div>
</template>

<style>
:root {
  color-scheme: dark;
  font-family: system-ui, "Noto Sans TC", sans-serif;
  background: #05070f;
  color: #d8e4ff;
}
body {
  margin: 0;
}
main {
  padding: 16px;
}
.global-loading {
  position: fixed;
  inset: 0 0 auto 0;
  height: 3px;
  background: linear-gradient(90deg, transparent, #38e1ff, transparent);
  background-size: 200% 100%;
  animation: erpcrm-loading 1.2s linear infinite;
}
@keyframes erpcrm-loading {
  from {
    background-position: 100% 0;
  }
  to {
    background-position: -100% 0;
  }
}
@media (prefers-reduced-motion: reduce) {
  .global-loading {
    animation: none;
    background: #38e1ff;
  }
}
.notice {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  padding: 8px 12px;
  margin-bottom: 8px;
  border: 1px solid currentColor;
}
.notice-error {
  color: #ff7a8a;
}
.notice-ok {
  color: #6dffb0;
}
.notice-pending {
  color: #ffd166;
}
</style>
