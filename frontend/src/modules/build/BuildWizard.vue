<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { useRouter } from "vue-router";
import {
  LAUNCH_KIT_FILENAME,
  launchKitUrl,
  moduleLabel,
  validateCompany,
  COMPANY_MAX,
  type BuildConfig,
} from "../../lib/modules";
import EmptyState from "../../ui/EmptyState.vue";
import HudPanel from "../../ui/HudPanel.vue";
import StatusSignal from "../../ui/StatusSignal.vue";
import StepProgress from "../../ui/StepProgress.vue";
import { useWorkspaceStore } from "../../stores/workspace";
import { defaultDraft, loadDraft, saveDraft, type Destination } from "./draft";
import ModuleChecklist from "./ModuleChecklist.vue";
import TemplateGrid from "./TemplateGrid.vue";
import { useBuilder } from "./useBuilder";

const STEPS = ["店名與行業", "確認推薦功能", "建立我的系統"];

const store = useWorkspaceStore();
const router = useRouter();

const config = ref<BuildConfig>({ industry: "", company: "", modules: [] });
const destination = ref<Destination>("public");
const b = useBuilder(config);

// ── 草稿：依部署預設值分開存在 sessionStorage（erpcrm.builder.v1.<scope>） ──
let draftReady = false;
watch(
  () => store.templates,
  (t) => {
    if (!t || t.items.length === 0) return;
    const draft = loadDraft(t, b.dependencies.value);
    config.value = { industry: draft.industry, company: draft.company, modules: draft.modules };
    destination.value = draft.destination;
    draftReady = true;
  },
  { immediate: true },
);
watch(
  [config, destination],
  () => {
    if (!draftReady || !store.templates) return;
    saveDraft(store.templates, { ...config.value, destination: destination.value }, b.dependencies.value);
  },
  { deep: true },
);

// ── 步驟 ──
const step = ref(0);
const reached = ref(0);
const heading = ref<HTMLElement | null>(null);
const companyTouched = ref(false);

const companyError = computed(() => validateCompany(config.value.company));
const shownCompanyError = computed(() => (companyTouched.value ? companyError.value : null));
const step1Valid = computed(() => !companyError.value && b.template.value !== null);

function canEnter(i: number): boolean {
  if (i === 0) return true;
  if (i > reached.value + 1) return false;
  if (!step1Valid.value) return false;
  if (i === 2) return b.configError.value === null;
  return true;
}

async function go(i: number): Promise<void> {
  if (i === step.value) return;
  if (i > step.value) companyTouched.value = true;
  if (!canEnter(i)) return;
  step.value = i;
  reached.value = Math.max(reached.value, i);
  await nextTick();
  heading.value?.focus();
}

function next(): void {
  void go(step.value + 1);
}
function back(): void {
  void go(step.value - 1);
}

function onCompany(event: Event): void {
  config.value = { ...config.value, company: (event.target as HTMLInputElement).value };
}

// ── 第 3 步 ──
const kitUrl = computed(() => launchKitUrl(config.value));
const kitReady = computed(() => !b.locked.value && b.configError.value === null);

function onKitDownload(): void {
  b.notice.value = "已開始下載本機啟動包。解壓縮到星軌 ERP-CRM 專案資料夾，再依包內 README.txt 啟動。";
}

function switchToLocal(): void {
  destination.value = "local";
}

function restart(): void {
  if (!store.templates || b.locked.value) return;
  const d = defaultDraft(store.templates, b.dependencies.value);
  config.value = { industry: d.industry, company: d.company, modules: d.modules };
  destination.value = d.destination;
  companyTouched.value = false;
  b.notice.value = "";
  b.localError.value = "";
  void go(0);
}

const destinationLabel = computed(() => (destination.value === "public" ? "直接在瀏覽器開始" : "下載本機啟動包"));
const companyShown = computed(() => config.value.company.trim() || "（尚未命名）");
</script>

<template>
  <div class="wizard" data-testid="page-build">
    <header class="wizard__head">
      <p class="wizard__eyebrow num">LAUNCH SEQUENCE · 01</p>
      <h1 class="wizard__title">三步建立你的星軌系統</h1>
      <p class="wizard__lead">
        取個名字、挑一個最接近的產業範本，確認推薦的功能就能開始。全程使用假商品與 SIM 測試幣，不會連線任何真實銀行、金流或發票。
      </p>
    </header>

    <HudPanel v-if="store.hasWorkspace" tone="warn" title="目前的工作區會完整保留" code="WS-OK" data-testid="build-existing">
      <p class="wizard__note">在這裡規劃另一套系統只會產生本機啟動包，不會影響你正在使用的工作區。</p>
      <template #actions>
        <button type="button" class="btn btn--sm" @click="router.push('/overview')">回到目前工作區</button>
      </template>
    </HudPanel>

    <EmptyState
      v-if="!store.templates || b.templates.value.length === 0"
      title="尚未取得產業範本"
      text="無法讀取範本目錄，請確認伺服器連線後重新讀取。"
    />
    <div v-if="!store.templates || b.templates.value.length === 0" class="wizard__retry">
      <button type="button" class="btn" :disabled="store.busy" @click="store.refresh()">重新讀取</button>
    </div>

    <template v-else>
      <StepProgress :steps="STEPS" :current="step" label="建置進度" />
      <ol class="wizard__tabs" aria-label="前往步驟">
        <li v-for="(s, i) in STEPS" :key="s">
          <button
            type="button"
            class="btn btn--sm btn--ghost"
            :aria-current="i === step ? 'step' : undefined"
            :disabled="i === step || (i > step && !canEnter(i)) || i > reached + 1"
            :data-step-tab="i"
            @click="go(i)"
          >
            {{ i + 1 }}．{{ s }}
          </button>
        </li>
      </ol>

      <p v-if="b.lockReason.value" class="wizard__lock" role="status">{{ b.lockReason.value }}</p>

      <div class="wizard__layout">
        <HudPanel :code="`STEP-0${step + 1}`" class="wizard__main">
          <h2 ref="heading" class="wizard__step-title" tabindex="-1" data-testid="step-heading">{{ STEPS[step] }}</h2>

          <!-- 第 1 步：店名與行業 -->
          <section v-if="step === 0" class="wizard__section">
            <label class="field">
              <span class="field__label">店名或公司名稱 *</span>
              <input
                :value="config.company"
                :maxlength="COMPANY_MAX"
                :disabled="b.locked.value"
                required
                autocomplete="organization"
                placeholder="例如：星軌示範商店"
                data-testid="company-input"
                :aria-invalid="shownCompanyError ? 'true' : 'false'"
                @input="onCompany"
                @blur="companyTouched = true"
              />
              <span v-if="shownCompanyError" class="wizard__error" role="alert">{{ shownCompanyError }}</span>
              <span v-else class="field__hint">最多 {{ COMPANY_MAX }} 個字，之後可以在報表與頁首看到。</span>
            </label>
            <div class="field">
              <span class="field__label">產業範本</span>
              <TemplateGrid
                :templates="b.templates.value"
                :selected="config.industry"
                :disabled="b.locked.value"
                @choose="b.chooseIndustry"
              />
              <span v-if="b.template.value" class="field__hint">{{ b.template.value.purpose }}</span>
            </div>
          </section>

          <!-- 第 2 步：確認推薦功能 -->
          <section v-else-if="step === 1" class="wizard__section">
            <div class="wizard__banner">
              <StatusSignal
                :tone="b.recommended.value ? 'ok' : 'info'"
                :label="b.recommended.value ? '推薦功能已選好' : '使用自訂功能組合'"
              />
              <button
                type="button"
                class="btn btn--sm"
                :disabled="b.recommended.value || b.locked.value"
                @click="b.restoreRecommended()"
              >
                恢復推薦功能
              </button>
            </div>
            <p class="field__hint">啟用流程模組時會自動補上它需要的模組；關閉必要模組時，依賴它的流程會一併關閉。</p>
            <ModuleChecklist
              :modules="config.modules"
              :disabled="b.locked.value"
              :dependencies="b.dependencies.value"
              @toggle="b.toggleModule"
            />
            <p v-if="b.notice.value" class="wizard__notice" role="status" data-testid="module-notice">{{ b.notice.value }}</p>
            <p v-if="b.configError.value" class="wizard__error" role="alert">{{ b.configError.value }}</p>
            <details v-if="b.template.value" class="wizard__details">
              <summary>{{ b.template.value.name }}範本內容</summary>
              <dl>
                <dt>用途</dt>
                <dd>{{ b.template.value.purpose }}</dd>
                <template v-if="b.template.value.terminology">
                  <dt>稱呼</dt>
                  <dd>
                    客戶稱為「{{ b.template.value.terminology.customer }}」、商品稱為「{{ b.template.value.terminology.product }}」、工單稱為「{{ b.template.value.terminology.work_order }}」
                  </dd>
                </template>
                <dt>推薦模組</dt>
                <dd>{{ b.template.value.modules.map(moduleLabel).join("、") }}</dd>
                <dt>範本版本</dt>
                <dd class="num">v{{ b.template.value.version }}</dd>
              </dl>
            </details>
          </section>

          <!-- 第 3 步：建立我的系統 -->
          <section v-else class="wizard__section">
            <dl class="wizard__summary" data-testid="build-summary">
              <dt>名稱</dt>
              <dd>{{ companyShown }}</dd>
              <dt>產業</dt>
              <dd>{{ b.template.value?.name }}</dd>
              <dt>模組</dt>
              <dd>{{ config.modules.map(moduleLabel).join("、") }}</dd>
            </dl>

            <fieldset class="wizard__dest" :disabled="b.locked.value">
              <legend class="field__label">開始的方式</legend>
              <label class="wizard__radio">
                <input v-model="destination" type="radio" value="public" name="destination" />
                <span><strong>直接在瀏覽器開始</strong><small>（推薦）在這台伺服器建立你的工作區，馬上可以操作。</small></span>
              </label>
              <label class="wizard__radio">
                <input v-model="destination" type="radio" value="local" name="destination" data-testid="dest-local" />
                <span><strong>下載本機啟動包</strong><small>在自己的電腦用 Docker 執行，需要 Docker Desktop 或 Docker Engine。</small></span>
              </label>
            </fieldset>

            <template v-if="destination === 'public'">
              <p class="field__hint">{{ b.retentionText.value }}</p>
              <div v-if="!store.hasWorkspace" class="wizard__actions">
                <button
                  type="button"
                  class="btn btn--primary"
                  :disabled="b.locked.value || b.configError.value !== null"
                  data-testid="build-create"
                  @click="b.create()"
                >
                  {{ b.creating.value ? "建立中…" : "建立我的系統" }}
                </button>
              </div>
              <div v-else class="wizard__actions">
                <button type="button" class="btn btn--primary" @click="router.push('/overview')">回到目前工作區</button>
                <button type="button" class="btn" @click="switchToLocal">下載另一套本機系統</button>
              </div>
            </template>

            <template v-else>
              <div class="wizard__actions">
                <a
                  v-if="kitReady"
                  class="btn btn--primary"
                  :href="kitUrl"
                  :download="LAUNCH_KIT_FILENAME"
                  data-testid="launch-kit"
                  @click="onKitDownload"
                >下載本機啟動包 ZIP</a>
                <button v-else type="button" class="btn btn--primary" disabled data-testid="launch-kit">下載本機啟動包 ZIP</button>
              </div>
              <details class="wizard__details" open>
                <summary>本機啟動步驟</summary>
                <ol class="wizard__howto">
                  <li>取得星軌 ERP-CRM 的專案資料夾（裡面有 <code>docker-compose.yaml</code>）。</li>
                  <li>把 ZIP 內的 <code>.env</code>、<code>start.sh</code>、<code>start.cmd</code>、<code>README.txt</code> 解壓縮到專案資料夾的最上層。</li>
                  <li>確認已安裝並啟動 Docker。</li>
                  <li>Windows 執行 <code>start.cmd</code>，macOS／Linux 執行 <code>./start.sh</code>（等同 <code>docker compose up -d --build</code>）。</li>
                  <li>開啟 <code>http://localhost:8080</code>，第一次進站會依這份設定自動建立工作區，資料永久保留在本機。</li>
                </ol>
              </details>
            </template>

            <p v-if="b.notice.value" class="wizard__notice" role="status">{{ b.notice.value }}</p>
            <p v-if="b.localError.value" class="wizard__error" role="alert">{{ b.localError.value }}</p>
          </section>

          <footer class="wizard__nav">
            <button type="button" class="btn btn--ghost" :disabled="step === 0" @click="back">上一步</button>
            <button type="button" class="btn btn--ghost btn--sm" :disabled="b.locked.value" @click="restart">重新開始</button>
            <button
              v-if="step < STEPS.length - 1"
              type="button"
              class="btn btn--primary"
              data-testid="build-next"
              @click="next"
            >
              下一步
            </button>
          </footer>
        </HudPanel>

        <HudPanel title="航線摘要" eyebrow="你的系統正在成形" code="PREVIEW" class="wizard__side" :heading-level="2">
          <dl class="wizard__summary">
            <dt>名稱</dt>
            <dd>{{ companyShown }}</dd>
            <dt>產業</dt>
            <dd>{{ b.template.value?.name ?? "—" }}</dd>
            <dt>開始方式</dt>
            <dd>{{ destinationLabel }}</dd>
            <dt>模組</dt>
            <dd class="num">{{ config.modules.length }} 個</dd>
          </dl>
          <ul class="wizard__chips">
            <li v-for="m in config.modules" :key="m" class="badge">{{ moduleLabel(m) }}</li>
          </ul>
          <p class="field__hint">
            想先看看能做什麼？<RouterLink to="/capabilities">功能地圖</RouterLink>列出 34 個工作領域的現況。
          </p>
          <p v-if="!store.hasWorkspace" class="field__hint">
            習慣一頁填完？改用<RouterLink to="/custom">自訂建置</RouterLink>表單。
          </p>
        </HudPanel>
      </div>
    </template>
  </div>
</template>

<style scoped>
.wizard {
  display: grid;
  gap: calc(var(--gap) * 1.5);
  max-width: 1200px;
}
.wizard__eyebrow {
  margin: 0;
  font-size: 0.72rem;
  letter-spacing: 0.24em;
  color: var(--accent);
}
.wizard__title {
  margin: 4px 0;
  font-size: clamp(1.5rem, 3vw, 2.1rem);
  text-shadow: 0 0 18px var(--glow);
}
.wizard__lead,
.wizard__note {
  margin: 0;
  max-width: 64ch;
  color: var(--ink-dim);
}
.wizard__retry {
  display: flex;
  justify-content: center;
}
.wizard__tabs {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.wizard__tabs [aria-current="step"] {
  border-color: var(--accent);
  color: var(--accent);
  opacity: 1;
}
.wizard__lock {
  margin: 0;
  color: var(--warn);
  font-size: 0.85rem;
}
.wizard__layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(220px, 300px);
  gap: var(--gap);
  align-items: start;
}
.wizard__step-title {
  margin: 0 0 var(--gap);
  font-size: 1.2rem;
}
.wizard__step-title:focus {
  outline: none;
  text-shadow: 0 0 12px var(--glow);
}
.wizard__section {
  display: grid;
  gap: var(--gap);
}
.wizard__banner {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  justify-content: space-between;
}
.wizard__notice {
  margin: 0;
  color: var(--info);
  font-size: 0.85rem;
}
.wizard__error {
  margin: 0;
  color: var(--danger);
  font-size: 0.85rem;
}
.wizard__details summary {
  cursor: pointer;
  color: var(--ink-dim);
}
.wizard__details dl,
.wizard__summary {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 4px 12px;
  margin: 8px 0 0;
}
.wizard__summary dt,
.wizard__details dt {
  color: var(--ink-faint);
  font-size: 0.8rem;
}
.wizard__summary dd,
.wizard__details dd {
  margin: 0;
  min-width: 0;
  overflow-wrap: anywhere;
}
.wizard__dest {
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  padding: 10px 12px;
  display: grid;
  gap: 8px;
  margin: 0;
}
.wizard__radio {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  cursor: pointer;
}
.wizard__radio input {
  width: auto;
  margin-top: 4px;
  accent-color: var(--accent);
}
.wizard__radio span {
  display: grid;
}
.wizard__radio small {
  color: var(--ink-dim);
}
.wizard__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.wizard__actions a.btn {
  text-decoration: none;
}
.wizard__howto {
  margin: 8px 0 0;
  padding-left: 1.4em;
  display: grid;
  gap: 4px;
  color: var(--ink-dim);
}
.wizard__howto code {
  font-family: var(--font-mono);
  color: var(--ink);
  overflow-wrap: anywhere;
}
.wizard__nav {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  margin-top: calc(var(--gap) * 1.5);
}
.wizard__chips {
  list-style: none;
  margin: 10px 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
@media (max-width: 860px) {
  .wizard__layout {
    grid-template-columns: 1fr;
  }
}
</style>
