<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { downloadFile } from "../../lib/download";
import { COMPANY_MAX, LAUNCH_KIT_FILENAME, launchKitUrl, validateCompany, type BuildConfig } from "../../lib/modules";
import EmptyState from "../../ui/EmptyState.vue";
import HudPanel from "../../ui/HudPanel.vue";
import { useWorkspaceStore } from "../../stores/workspace";
import { defaultDraft, draftFromQuery } from "./draft";
import ModuleChecklist from "./ModuleChecklist.vue";
import TemplateGrid from "./TemplateGrid.vue";
import { useBuilder } from "./useBuilder";

/**
 * 自訂建置：單頁表單（選產業 → 調整模組 → 開始模擬）。
 * 已有工作區時（設定頁「切換產業範本」），按鈕改為「先清除目前工作區」，設定有效才發出 `request-clear`（帶著選好的設定）。
 * 路由帶有 industry／company／modules 時（清除後由設定頁導入），以草稿規則驗證後預選。
 */
const emit = defineEmits<{ "request-clear": [config: BuildConfig] }>();

const store = useWorkspaceStore();
const route = useRoute();
const config = ref<BuildConfig>({ industry: "", company: "", modules: [] });
const b = useBuilder(config);

watch(
  () => store.templates,
  (t) => {
    if (!t || t.items.length === 0 || config.value.industry) return;
    const ids = t.items.map((x) => x.id);
    const d = draftFromQuery(route.query, ids, b.dependencies.value) ?? defaultDraft(t, b.dependencies.value);
    config.value = { industry: d.industry, company: d.company, modules: d.modules };
  },
  { immediate: true },
);

const companyTouched = ref(false);
const companyError = computed(() => (companyTouched.value ? validateCompany(config.value.company) : null));
const kitUrl = computed(() => launchKitUrl(config.value));
const kitBusy = ref(false);

async function downloadKit(): Promise<void> {
  if (kitBusy.value) return;
  kitBusy.value = true;
  b.notice.value = "";
  b.localError.value = "";
  try {
    const error = await downloadFile(kitUrl.value, LAUNCH_KIT_FILENAME);
    if (error) b.localError.value = error;
    else b.notice.value = "已下載本機啟動包。解壓縮到星軌 ERP-CRM 專案資料夾，再依包內 README.txt 啟動。";
  } finally {
    kitBusy.value = false;
  }
}
const ready = computed(() => !b.locked.value && b.configError.value === null);

function onCompany(event: Event): void {
  config.value = { ...config.value, company: (event.target as HTMLInputElement).value };
}

function submit(): void {
  companyTouched.value = true;
  if (store.hasWorkspace) {
    b.localError.value = b.configError.value ?? "";
    if (!b.locked.value && !b.configError.value) emit("request-clear", { ...config.value, modules: [...config.value.modules] });
    return;
  }
  void b.create();
}
</script>

<template>
  <div class="custom" data-testid="page-custom">
    <header class="custom__head">
      <div>
        <p class="custom__eyebrow num">MANUAL CONFIG · 02</p>
        <h1 class="custom__title">自訂建置</h1>
        <p class="custom__lead">
          用一張表單決定名稱、產業範本與要啟用的模組。資料全是假商品與 SIM 測試幣，沒有真銀行、金流或發票連線。
        </p>
        <p class="custom__lead">{{ b.retentionText.value }}</p>
      </div>
      <ol class="custom__strip" aria-label="流程">
        <li>選產業</li>
        <li>調整模組</li>
        <li>開始模擬</li>
      </ol>
    </header>

    <EmptyState v-if="b.templates.value.length === 0" title="尚未取得產業範本" text="請確認伺服器連線後重新讀取。" />

    <HudPanel v-else :title="store.hasWorkspace ? '建立另一套範本' : '建立我的系統'" code="CFG-02">
      <form class="custom__form" @submit.prevent="submit">
        <p v-if="store.hasWorkspace" class="custom__warn">切換範本會清除目前的資料，請先到設定頁匯出 JSON 備份。</p>

        <label class="field">
          <span class="field__label">店名或公司名稱 *</span>
          <input
            :value="config.company"
            :maxlength="COMPANY_MAX"
            :disabled="b.locked.value"
            required
            data-testid="custom-company"
            @input="onCompany"
            @blur="companyTouched = true"
          />
          <span v-if="companyError" class="custom__error" role="alert">{{ companyError }}</span>
        </label>

        <fieldset class="custom__fieldset">
          <legend class="field__label">產業範本</legend>
          <TemplateGrid
            :templates="b.templates.value"
            :selected="config.industry"
            :disabled="b.locked.value"
            @choose="b.chooseIndustry"
          />
          <p v-if="b.template.value" class="field__hint">{{ b.template.value.purpose }}</p>
        </fieldset>

        <fieldset class="custom__fieldset">
          <legend class="field__label">啟用功能</legend>
          <p class="field__hint">啟用流程會一併啟用必要模組；關閉必要模組會同時關閉相依流程。</p>
          <ModuleChecklist
            :modules="config.modules"
            :disabled="b.locked.value"
            :dependencies="b.dependencies.value"
            @toggle="b.toggleModule"
          />
        </fieldset>

        <p v-if="b.notice.value" class="custom__notice" role="status" data-testid="custom-notice">{{ b.notice.value }}</p>
        <p v-if="b.lockReason.value" class="custom__warn" role="status">{{ b.lockReason.value }}</p>
        <p v-if="b.localError.value" class="custom__error" role="alert">{{ b.localError.value }}</p>

        <div class="custom__actions">
          <button
            type="submit"
            class="btn btn--primary"
            :disabled="b.locked.value || (!store.hasWorkspace && b.configError.value !== null)"
            data-testid="custom-create"
          >
            {{ b.creating.value ? "建立中…" : store.hasWorkspace ? "先清除目前工作區" : "建立我的系統" }}
          </button>
          <button type="button" class="btn" :disabled="!ready || kitBusy" data-testid="custom-launch-kit" @click="downloadKit">
            {{ kitBusy ? "下載中…" : "下載本機啟動包" }}
          </button>
        </div>
        <p class="field__hint">
          本機啟動包內含 docker compose 用的 <code>.env</code> 與啟動說明；解壓縮到專案資料夾後執行 <code>docker compose up -d --build</code>。
        </p>
      </form>
    </HudPanel>
  </div>
</template>

<style scoped>
.custom {
  display: grid;
  gap: calc(var(--gap) * 1.5);
  max-width: 1100px;
}
.custom__head {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: var(--gap);
  align-items: end;
}
.custom__eyebrow {
  margin: 0;
  font-size: 0.72rem;
  letter-spacing: 0.24em;
  color: var(--accent);
}
.custom__title {
  margin: 4px 0;
  font-size: clamp(1.5rem, 3vw, 2.1rem);
  text-shadow: 0 0 18px var(--glow);
}
.custom__lead {
  margin: 0 0 4px;
  max-width: 64ch;
  color: var(--ink-dim);
}
.custom__strip {
  list-style: none;
  display: flex;
  gap: 6px;
  margin: 0;
  padding: 0;
  font-size: 0.85rem;
}
.custom__strip li {
  padding: 4px 10px;
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-sm);
}
.custom__strip li + li::before {
  content: "→ ";
  color: var(--accent);
}
.custom__form {
  display: grid;
  gap: calc(var(--gap) * 1.25);
}
.custom__fieldset {
  border: 0;
  padding: 0;
  margin: 0;
  display: grid;
  gap: 8px;
  min-width: 0;
}
.custom__notice {
  margin: 0;
  color: var(--info);
  font-size: 0.85rem;
}
.custom__warn {
  margin: 0;
  color: var(--warn);
  font-size: 0.85rem;
}
.custom__error {
  margin: 0;
  color: var(--danger);
  font-size: 0.85rem;
}
.custom__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.custom__actions a.btn {
  text-decoration: none;
}
code {
  font-family: var(--font-mono);
}
</style>
