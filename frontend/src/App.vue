<script setup lang="ts">
import { computed, watch } from "vue";
import { RouterView, useRoute, useRouter } from "vue-router";
import { pendingStorageVolatile } from "./api/pending";
import GlobalSearch from "./modules/overview/GlobalSearch.vue";
import QuickCreate from "./modules/overview/QuickCreate.vue";
import { useUiStore } from "./stores/ui";
import { NO_VIEW_BLOCKED, useWorkspaceStore } from "./stores/workspace";
import AppShell from "./ui/AppShell.vue";
import Toast from "./ui/Toast.vue";

const store = useWorkspaceStore();
const ui = useUiStore();
const route = useRoute();
const router = useRouter();
const volatile = computed(() => store.pending !== null && pendingStorageVolatile());
const targeted = computed(
  () =>
    (route.name === "module" || route.name === "administration") &&
    typeof route.query.target === "string" &&
    route.query.target !== "",
);

// 讀取失敗後重新讀取成功：以目前路由重新導覽一次，讓守衛依實際狀態決定（例如沒有工作區時前往 /build）。
watch(
  () => store.loadFailed,
  (failed, was) => {
    if (was && !failed) void router.replace({ path: route.path, query: route.query, hash: route.hash, force: true });
  },
);

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
        <Toast v-if="store.error && !store.loadFailed" tone="danger" title="操作尚未完成">
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
    <section v-else-if="store.loadFailed" class="app-failed" role="alert" data-testid="load-failed">
      <h1 class="app-failed__title">無法取得工作區狀態</h1>
      <p>{{ store.error || NO_VIEW_BLOCKED }}</p>
      <p class="app-failed__note">工作區資料沒有變動，請稍候再按「重新讀取」。</p>
      <button type="button" class="btn btn--primary" data-testid="load-retry" :disabled="store.busy" @click="store.refresh()">
        重新讀取
      </button>
    </section>
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
.app-failed {
  display: grid;
  gap: 12px;
  justify-items: start;
  max-width: 560px;
  padding: 16px 18px;
  border-left: 3px solid var(--danger);
  background: color-mix(in srgb, var(--danger) 8%, transparent);
}
.app-failed p {
  margin: 0;
}
.app-failed__title {
  margin: 0;
  font-family: var(--font-display);
  font-size: 1.1rem;
}
.app-failed__note {
  color: var(--ink-dim);
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
