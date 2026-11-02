<script setup lang="ts">
import { computed } from "vue";
import type { RoleCard, RoleViewId } from "../../api/types";
import { ROLE_VIEWS, useUiStore } from "../../stores/ui";
import { useWorkspaceStore } from "../../stores/workspace";
import Gauge from "../../ui/Gauge.vue";
import HudPanel from "../../ui/HudPanel.vue";
import { pageLabel } from "./labels";

/**
 * 你的日常工作台（F§5）：工作視角只調整首頁重點，不改變功能或權限。
 * 卡片與流程由後端 `GET /workbench` 的 roles 計算；點選只開啟頁面，處理中、待確認或試看時停用。
 */
const store = useWorkspaceStore();
const ui = useUiStore();

const locked = computed(() => store.busy || Boolean(store.pending) || store.designPreview);
const model = computed(() => store.workbench?.roles?.[ui.roleView] ?? null);
const current = computed(() => ROLE_VIEWS.find((r) => r.id === ui.roleView) ?? ROLE_VIEWS[0]);
const cards = computed<RoleCard[]>(() => (model.value?.cards ?? []).slice(0, 4));
const total = computed(() => cards.value.reduce((sum, c) => sum + Math.max(0, c.count), 0));
const steps = computed(() =>
  (model.value?.flow?.steps ?? []).map((s) =>
    typeof s === "string" ? { module: s, label: pageLabel(s) } : { module: s.module, label: s.label || pageLabel(s.module) },
  ),
);

function select(id: RoleViewId): void {
  if (locked.value) return;
  ui.setRoleView(id);
}

function openCard(card: RoleCard): void {
  if (card.target) void ui.navigateTo(card.target);
  else void ui.navigateModule(card.module);
}
</script>

<template>
  <HudPanel title="你的日常工作台" code="ROLE-DECK" eyebrow="今天要處理什麼？" data-testid="role-center">
    <template #actions>
      <button type="button" class="btn btn--ghost btn--sm" data-testid="role-open-capabilities" :disabled="locked" @click="ui.navigateModule('capabilities')">
        找功能
      </button>
    </template>
    <div class="segmented rc__views" role="group" aria-label="工作視角">
      <button
        v-for="r in ROLE_VIEWS"
        :key="r.id"
        type="button"
        :data-testid="`role-view-${r.id}`"
        :aria-pressed="ui.roleView === r.id ? 'true' : 'false'"
        :disabled="locked || !ui.roleAvailable(r.id)"
        :title="r.description"
        @click="select(r.id)"
      >
        {{ r.name }}<small v-if="!ui.roleAvailable(r.id)" class="rc__na">需啟用相關功能</small>
      </button>
    </div>
    <p class="ov-note rc__note">只調整首頁的工作視角，不會改變功能或帳號權限。</p>

    <h3 class="rc__heading">{{ current.name }}的工作重點 <span class="ov-count">依目前模擬資料計算</span></h3>
    <p v-if="!model" class="ov-empty">工作重點暫時無法取得，請按「重新讀取」後再試。</p>
    <ul v-else-if="cards.length" class="ov-grid rc__cards">
      <li v-for="c in cards" :key="c.id" class="rc__card">
        <Gauge :value="c.count" :max="total" :label="`${c.label}佔比`" unit="%" />
        <button type="button" class="ov-tile rc__open" :data-testid="`role-card-${c.id}`" :disabled="locked" @click="openCard(c)">
          <span class="ov-tile__title">{{ c.label }}</span>
          <span class="rc__count num">{{ c.count }}<small>{{ c.unit }}</small></span>
          <span class="ov-tile__text">{{ c.description }}</span>
          <span class="ov-tile__meta">查看資料 ↗</span>
        </button>
      </li>
    </ul>
    <p v-else class="ov-empty">這個視角目前沒有需要追蹤的數字。</p>

    <div v-if="model?.flow" class="rc__flow" :data-testid="`role-flow-${model.flow.id ?? 'flow'}`">
      <h3 class="rc__heading">{{ model.flow.title }}</h3>
      <p v-if="model.flow.description" class="ov-tile__text">{{ model.flow.description }}</p>
      <ol class="rc__steps" aria-label="流程入口">
        <li v-for="(s, i) in steps" :key="s.module">
          <button type="button" class="ov-tile rc__step" :data-testid="`role-flow-step-${s.module}`" :disabled="locked" @click="ui.navigateModule(s.module)">
            <span class="rc__step-no num" aria-hidden="true">{{ String(i + 1).padStart(2, "0") }}</span>
            <span class="ov-tile__title">{{ s.label }}</span>
          </button>
        </li>
      </ol>
      <p class="ov-note">這些入口只開啟對應頁面；付款、進貨、出貨與行政申請都需要你另外確認。</p>
    </div>
  </HudPanel>
</template>

<style scoped src="./overview.css"></style>
<style scoped>
.rc__views {
  flex-wrap: wrap;
}
.rc__na {
  display: block;
  font-size: 0.7rem;
  color: var(--ink-faint);
}
.rc__note {
  margin-top: 6px;
}
.rc__heading {
  margin: 16px 0 8px;
  font-size: 1rem;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: baseline;
}
.rc__card {
  display: grid;
  gap: 8px;
  justify-items: center;
  padding: 10px 8px;
  border: 1px solid var(--line);
  background: color-mix(in srgb, var(--surface-2) 40%, transparent);
}
.rc__open {
  text-align: center;
  justify-items: center;
}
.rc__count {
  font-size: 1.5rem;
  font-weight: 600;
}
.rc__count small {
  margin-left: 4px;
  font-size: 0.8rem;
  color: var(--ink-dim);
}
.rc__steps {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 8px;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 180px), 1fr));
}
.rc__step {
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
}
.rc__step-no {
  color: var(--accent);
  font-size: 0.8rem;
}
</style>
