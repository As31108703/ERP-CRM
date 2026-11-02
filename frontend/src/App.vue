<script setup lang="ts">
import { computed } from "vue";
import { RouterView, useRoute, useRouter } from "vue-router";
import { pendingStorageVolatile } from "./api/pending";
import GlobalSearch from "./modules/overview/GlobalSearch.vue";
import QuickCreate from "./modules/overview/QuickCreate.vue";
import { useUiStore } from "./stores/ui";
import { useWorkspaceStore } from "./stores/workspace";
import AppShell from "./ui/AppShell.vue";
import Toast from "./ui/Toast.vue";

const store = useWorkspaceStore();
const ui = useUiStore();
const route = useRoute();
const router = useRouter();
const volatile = computed(() => store.pending !== null && pendingStorageVolatile());
const targeted = computed(() => route.name === "module" && typeof route.query.target === "string" && route.query.target !== "");

function clearTarget(): void {
  const query = { ...route.query };
  delete query.target;
  void router.replace({ query });
}
</script>

<template>
  <AppShell @search="ui.openSearch()" @quick-create="ui.openQuickCreate()">
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
        <Toast v-if="targeted" tone="info" data-testid="target-notice">
          已定位到指定紀錄，篩選已清除。
          <template #actions>
            <button type="button" class="btn btn--sm" data-testid="target-clear" @click="clearTarget">清除定位</button>
          </template>
        </Toast>
      </template>
    </template>
    <p v-if="!store.loaded" class="app-loading">
      <span class="app-loading__orbit" aria-hidden="true" />
      準備你的測試工作區
    </p>
    <RouterView v-else />
    <template v-if="store.loaded && store.hasWorkspace">
      <GlobalSearch />
      <QuickCreate />
    </template>
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
