<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { ApiError, get, preference } from "../../api/client";
import type {
  LearningDetail,
  LearningListing,
  LearningPathId,
  LearningSession,
  LearningViewPatch,
} from "../../api/types";
import { moduleLabel } from "../../lib/modules";
import { modulePath, targetLocation } from "../../lib/records";
import { useWorkspaceStore } from "../../stores/workspace";
import EmptyState from "../../ui/EmptyState.vue";
import HudPanel from "../../ui/HudPanel.vue";
import StepProgress from "../../ui/StepProgress.vue";
import ActionDock from "./ActionDock.vue";
import ChapterList from "./ChapterList.vue";
import FlowDiagram from "./FlowDiagram.vue";
import QuizCard from "./QuizCard.vue";
import RoutePicker, { type RouteCard } from "./RoutePicker.vue";
import ScenePanel from "./ScenePanel.vue";
import {
  canExecute as canExecuteStep,
  confirmedCount,
  currentIndexOf,
  currentNodeIndex,
  LEARNING_API,
  NOTICES,
  recordTarget,
  scopeLabel,
} from "./learning";

/**
 * 沉浸式流程教學（F§3 Studio UI）。進度、證據、前後讀值都由伺服器計算；
 * 開始／另開一輪／閱讀偏好是不改版本的偏好寫入，執行一步走一般命令管線。
 */
const store = useWorkspaceStore();
const router = useRouter();

const listing = ref<LearningListing | null>(null);
const details = reactive<Partial<Record<LearningPathId, LearningDetail>>>({});
const selected = ref<LearningPathId | null>(null);
const loading = ref(true);
const loadError = ref("");
const localBusy = ref(false);
const notice = ref("");
const actionError = ref("");
const reducedMotion = ref(false);
const scene = ref<InstanceType<typeof ScenePanel> | null>(null);

/** 還沒開始的路線沒有 session，閱讀偏好先留在本頁。 */
const localView = reactive<Omit<LearningSession, "id" | "path" | "run_id" | "active" | "created_at" | "updated_at">>({
  paused: false,
  scope: "lesson",
  compact: false,
  quiz_choice: null,
  selected_step: null,
});

const ws = computed(() => store.view?.workspace ?? null);
const detail = computed<LearningDetail | null>(() => (selected.value ? details[selected.value] ?? null : null));
const session = computed(() => detail.value?.session ?? null);
const view = computed(() => session.value ?? localView);

const steps = computed(() => detail.value?.path.steps ?? []);
const evaluation = computed(() => detail.value?.evaluation ?? null);
const currentIndex = computed(() => {
  const d = detail.value;
  if (!d) return 0;
  if (d.session) return currentIndexOf(d);
  const at = localView.selected_step ? d.evaluation.steps.findIndex((s) => s.id === localView.selected_step) : -1;
  return at >= 0 ? at : currentIndexOf(d);
});
const nextIndex = computed(() => evaluation.value?.next_index ?? 0);
const currentStep = computed(() => steps.value[currentIndex.value] ?? null);
const currentEval = computed(() => evaluation.value?.steps[currentIndex.value] ?? null);
const total = computed(() => steps.value.length);
const confirmed = computed(() => (detail.value ? confirmedCount(detail.value) : 0));
const complete = computed(() => Boolean(evaluation.value?.complete));

const busy = computed(() => store.busy || localBusy.value);
const pending = computed(() => Boolean(store.pending));
const lockReason = computed(() => store.blockedReason());
const readingPast = computed(() => Boolean(currentEval.value?.complete));
const readingAhead = computed(() => currentIndex.value > nextIndex.value);
const atCurrent = computed(() => !readingPast.value && !readingAhead.value);

const canExecute = computed(() => {
  const d = detail.value;
  if (!d || lockReason.value) return false;
  return canExecuteStep(d, currentIndex.value, { busy: busy.value, pending: pending.value });
});

const sceneState = computed(() => {
  if (!session.value) return "尚未開始";
  if (currentEval.value?.complete) return "已確認";
  if (readingAhead.value) return "閱讀預覽";
  if (view.value.paused) return "已暫停";
  return "準備實作";
});

const previewText = computed(() =>
  session.value && atCurrent.value && currentIndex.value === nextIndex.value ? detail.value?.preview.text ?? null : null,
);
const blockedReason = computed(() =>
  session.value && atCurrent.value && currentIndex.value === nextIndex.value ? detail.value?.preview.blocked_reason ?? null : null,
);
const snapshot = computed(() => (currentStep.value ? detail.value?.snapshots[currentStep.value.id] ?? null : null));
const facts = computed(() => detail.value?.facts[view.value.scope] ?? []);
const nodeIndex = computed(() => (detail.value ? currentNodeIndex(detail.value, currentIndex.value) : -1));
const still = computed(() => view.value.paused || reducedMotion.value);

const routes = computed<RouteCard[]>(() =>
  (listing.value?.available_paths ?? []).flatMap((id) => {
    const d = details[id];
    if (!d) return [];
    const saved = listing.value?.sessions.find((s) => s.path === id);
    return [
      {
        id,
        title: d.path.title,
        subtitle: d.path.subtitle,
        confirmed: d.session ? confirmedCount(d) : saved?.confirmed ?? 0,
        total: d.path.steps.length,
      },
    ];
  }),
);

function messageOf(err: unknown): string {
  return err instanceof ApiError ? err.message : "發生未預期的錯誤，請重新讀取。";
}

async function fetchDetail(id: LearningPathId): Promise<void> {
  details[id] = await get<LearningDetail>(LEARNING_API.detail(id));
}

async function load(): Promise<void> {
  loading.value = true;
  loadError.value = "";
  try {
    const list = await get<LearningListing>(LEARNING_API.listing);
    listing.value = list;
    for (const key of Object.keys(details) as LearningPathId[]) {
      if (!list.available_paths.includes(key)) delete details[key];
    }
    const results = await Promise.allSettled(list.available_paths.map((id) => fetchDetail(id)));
    const failed = results.find((r): r is PromiseRejectedResult => r.status === "rejected");
    if (failed) loadError.value = messageOf(failed.reason);
    const keep = selected.value && list.available_paths.includes(selected.value) ? selected.value : null;
    selected.value = keep ?? list.active ?? list.available_paths[0] ?? null;
  } catch (err) {
    loadError.value = messageOf(err);
  } finally {
    loading.value = false;
  }
}

async function reloadCurrent(): Promise<void> {
  const id = selected.value;
  if (!id) return;
  try {
    await fetchDetail(id);
    listing.value = await get<LearningListing>(LEARNING_API.listing);
  } catch (err) {
    actionError.value = messageOf(err);
  }
}

/** 偏好寫入：鎖定本頁、成功時以回應的 detail 取代畫面。 */
async function prefer(call: () => Promise<LearningDetail>, success = ""): Promise<boolean> {
  if (localBusy.value) return false;
  localBusy.value = true;
  actionError.value = "";
  try {
    const next = await call();
    details[next.path.id] = next;
    if (success) notice.value = success;
    return true;
  } catch (err) {
    actionError.value = messageOf(err);
    await reloadCurrent();
    return false;
  } finally {
    localBusy.value = false;
  }
}

async function selectRoute(id: LearningPathId): Promise<void> {
  if (busy.value || pending.value) return;
  if (id === selected.value && session.value) return;
  const ok = await prefer(() => preference<LearningDetail>("POST", LEARNING_API.start(id), {}), NOTICES.switched);
  if (ok) selected.value = id;
}

async function startCurrent(): Promise<void> {
  if (!selected.value || busy.value || pending.value) return;
  const id = selected.value;
  await prefer(() => preference<LearningDetail>("POST", LEARNING_API.start(id), {}));
  // 開始前在本頁調整過的閱讀偏好一併寫入本輪
  const started = session.value;
  if (!started) return;
  const patch: LearningViewPatch = {};
  for (const key of ["paused", "scope", "compact", "quiz_choice", "selected_step"] as const) {
    if (localView[key] !== started[key]) Object.assign(patch, { [key]: localView[key] });
  }
  if (Object.keys(patch).length) await updateView(patch);
}

async function restart(): Promise<void> {
  if (!selected.value || !session.value || busy.value || pending.value) return;
  const id = selected.value;
  await prefer(() => preference<LearningDetail>("POST", LEARNING_API.restart(id), {}), NOTICES.restarted);
}

/** 閱讀偏好：先更新畫面，再寫入伺服器；沒有 session 時只留在本頁。 */
async function updateView(patch: LearningViewPatch, success = ""): Promise<void> {
  const id = selected.value;
  const d = detail.value;
  // 另一個寫入進行中時不接受新的偏好，避免先翻轉畫面又被回應蓋掉
  if (!id || !d || localBusy.value) return;
  if (!d.session) {
    Object.assign(localView, patch);
    if (success) notice.value = success;
    return;
  }
  details[id] = { ...d, session: { ...d.session, ...patch } };
  await prefer(() => preference<LearningDetail>("PATCH", LEARNING_API.view(id), patch), success);
}

function focusScene(): void {
  void nextTick(() => scene.value?.focus(!reducedMotion.value));
}

async function selectStep(stepId: string): Promise<void> {
  if (busy.value) return;
  await updateView({ selected_step: stepId }, NOTICES.reading);
  focusScene();
}

async function goCurrent(): Promise<void> {
  if (busy.value) return;
  await updateView({ selected_step: null });
  focusScene();
}

async function togglePause(): Promise<void> {
  const paused = !view.value.paused;
  await updateView({ paused }, paused ? NOTICES.paused : NOTICES.resumed);
}

async function execute(): Promise<void> {
  const id = selected.value;
  const step = currentStep.value;
  if (!id || !step || !canExecute.value) return;
  localBusy.value = true;
  actionError.value = "";
  notice.value = NOTICES.running;
  try {
    const result = await store.run("POST", LEARNING_API.execute(id), { step_id: step.id });
    notice.value = result ? NOTICES.confirmed : NOTICES.unconfirmed;
    await reloadCurrent();
  } finally {
    localBusy.value = false;
  }
}

async function inspect(): Promise<void> {
  const d = detail.value;
  const step = currentStep.value;
  if (!d || !step) return;
  const target = recordTarget(d, currentIndex.value, ws.value);
  await router.push(target ? targetLocation(target) : modulePath(step.nav));
}

function goTo(path: string): void {
  void router.push(path);
}

// 其他頁面或「確認原操作結果」改變了版本時，重新讀取目前路線的證據
watch(
  () => store.view?.version,
  (next, prev) => {
    if (prev !== undefined && next !== prev && !localBusy.value) void reloadCurrent();
  },
);
watch(
  () => ws.value?.generation_id,
  (next, prev) => {
    if (prev !== undefined && next !== prev) {
      selected.value = null;
      void load();
    }
  },
);

let motionQuery: MediaQueryList | null = null;
const onMotion = () => {
  reducedMotion.value = Boolean(motionQuery?.matches);
};

onMounted(() => {
  if (typeof window.matchMedia === "function") {
    motionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    onMotion();
    motionQuery.addEventListener?.("change", onMotion);
  }
  void load();
});
onBeforeUnmount(() => motionQuery?.removeEventListener?.("change", onMotion));
</script>

<template>
  <div class="studio" :class="{ 'is-compact': view.compact }" data-testid="learning-studio">
    <header class="studio__top">
      <div>
        <p class="studio__code num" aria-hidden="true">SIM-ACADEMY · FLIGHT DECK</p>
        <p class="studio__kicker">
          <span class="badge badge--accent">SIM 實作教學</span>
          <span>{{ ws?.company_name }}</span>
        </p>
      </div>
      <button type="button" class="btn btn--ghost" data-testid="learning-exit" @click="goTo('/overview')">回工作總覽 ↗</button>
    </header>

    <p v-if="loading && !listing" class="studio__loading" role="status">正在讀取教學路線…</p>
    <p v-if="loadError" class="studio__error" role="alert">{{ loadError }}</p>

    <HudPanel v-if="listing && !listing.available_paths.length" title="先啟用一條完整工作流程" code="NO-ROUTE" tone="warn">
      <EmptyState title="目前沒有可用的教學路線" text="教學路線需要對應的模組全部啟用：">
        <ul class="studio__reqs">
          <li v-for="p in listing.paths ?? []" :key="p.id" :data-testid="`learning-requirement-${p.id}`">
            {{ p.title }}：需要{{ p.modules.map(moduleLabel).join("、") }}。
          </li>
        </ul>
        <div class="studio__row">
          <button type="button" class="btn" @click="goTo('/settings')">查看模組設定</button>
          <button type="button" class="btn btn--ghost" @click="goTo('/overview')">回工作總覽</button>
        </div>
      </EmptyState>
    </HudPanel>

    <template v-else-if="detail && currentStep && currentEval && evaluation">
      <RoutePicker :routes="routes" :selected="selected" :disabled="busy || pending" @select="selectRoute" />

      <div class="studio__tools">
        <div class="segmented" role="group" aria-label="教學資料範圍">
          <button
            type="button"
            data-testid="learning-scope-lesson"
            :aria-pressed="view.scope === 'lesson'"
            :disabled="busy"
            @click="updateView({ scope: 'lesson' })">
            本輪練習
          </button>
          <button
            type="button"
            data-testid="learning-scope-workspace"
            :aria-pressed="view.scope === 'workspace'"
            :disabled="busy"
            @click="updateView({ scope: 'workspace' })"
          >
            整個工作區
          </button>
        </div>
        <button type="button" class="btn btn--sm" data-testid="learning-compact" :aria-pressed="view.compact" :disabled="busy" @click="updateView({ compact: !view.compact })">
          {{ view.compact ? "展開教學畫面" : "精簡教學畫面" }}
        </button>
        <button type="button" class="btn btn--sm" :data-testid="view.paused ? 'learning-resume' : 'learning-pause'" :disabled="busy" @click="togglePause">
          {{ view.paused ? "繼續教學 ▷" : "暫停教學 ⏸" }}
        </button>
        <button
          type="button"
          class="btn btn--sm btn--ghost"
          data-testid="learning-restart"
          :disabled="!session || busy || pending"
          title="另開一輪會建立新的教學索引，現有客戶、庫存與流水都會保留。"
          @click="restart"
        >
          另開一輪練習
        </button>
      </div>

      <HudPanel :eyebrow="`${detail.path.title} · 用你的工作區實作`" code="FLOW-MAP" tone="accent" class="studio__theatre">
        <div class="studio__opening">
          <h1 class="studio__headline">{{ detail.path.headline }}</h1>
          <p class="studio__intro">{{ detail.path.intro }}</p>
        </div>
        <FlowDiagram
          class="studio__diagram"
          :title="detail.path.title"
          :nodes="detail.path.nodes"
          :facts="facts"
          :current="nodeIndex"
          :still="still"
        />
        <footer class="studio__theatre-foot">
          <span>{{ detail.path.outcome }}</span>
          <span class="studio__live num">
            <i aria-hidden="true" :class="{ 'is-still': still }" />
            {{ scopeLabel(view.scope) }} · 版本 {{ store.view?.version ?? 0 }}
          </span>
        </footer>
        <p class="studio__motion">
          {{ reducedMotion ? "減少動態已開啟，圖示保持靜止。" : view.paused ? "已暫停，示意動畫停止。" : "示意動畫不會自動操作資料。" }}
        </p>
      </HudPanel>

      <section class="studio__progress" data-testid="learning-progress">
        <StepProgress :steps="steps.map((s) => s.title)" :current="nextIndex" label="已確認的教學步驟" />
        <p class="studio__progress-text">
          <strong class="num">{{ confirmed }}／{{ total }} 步驟已確認</strong>
          <span>{{ complete ? "這條流程已有完整操作證據。" : "完成以實際操作與資料狀態為準。" }}</span>
          <span v-if="complete" class="badge badge--accent" data-testid="learning-complete">流程已完成 ✓</span>
        </p>
      </section>

      <div class="studio__chapters">
        <ChapterList
          :steps="steps"
          :evaluation="evaluation.steps"
          :current="currentIndex"
          :next="nextIndex"
          :disabled="busy"
          @select="selectStep"
        />
        <HudPanel code="SCENE" class="studio__scene">
          <ScenePanel
            ref="scene"
            :step="currentStep"
            :evaluation="currentEval"
            :index="currentIndex"
            :total="total"
            :state="sceneState"
            :preview-text="previewText"
            :blocked-reason="blockedReason"
            :snapshot="snapshot"
          >
            <ActionDock
              :has-session="Boolean(session)"
              :can-execute="canExecute"
              :reading-past="readingPast"
              :reading-ahead="readingAhead"
              :complete="complete"
              :paused="view.paused"
              :pending="pending"
              :busy="busy"
              :disabled="busy"
              @execute="execute"
              @start="startCurrent"
              @next="goCurrent"
              @back="goCurrent"
              @inspect="inspect"
            />
            <p class="studio__notice" role="status" aria-live="polite">{{ notice }}</p>
            <p v-if="actionError || store.error" class="studio__error" role="alert">{{ actionError || store.error }}</p>
          </ScenePanel>
        </HudPanel>
      </div>

      <div class="studio__bottom">
        <HudPanel code="QUIZ" :heading-level="2">
          <QuizCard
            :quiz="detail.path.quiz"
            :path-id="detail.path.id"
            :choice="view.quiz_choice"
            :disabled="busy"
            @choose="(i) => updateView({ quiz_choice: i as 0 | 1 | 2 })"
          />
        </HudPanel>
        <HudPanel
          :eyebrow="view.scope === 'lesson' ? '本輪練習的資料' : '整個工作區的資料'"
          :title="ws?.company_name ?? ''"
          code="LIVE-DATA"
          data-testid="learning-live-facts"
        >
          <dl class="studio__facts">
            <div v-for="f in facts" :key="f.label">
              <dt>{{ f.label }}</dt>
              <dd class="num">{{ f.value }}</dd>
            </div>
          </dl>
          <p class="studio__facts-note">
            {{
              view.scope === "lesson"
                ? "本輪紀錄以這次教學的操作來源辨認，商品庫存與商家測試幣共用並另標示。"
                : "數字涵蓋種子資料及其他練習。教學完成證據仍只核對本輪操作。"
            }}
          </p>
        </HudPanel>
      </div>

      <HudPanel v-if="complete" tone="accent" code="MISSION-CLEAR" class="studio__finish" data-testid="learning-finish">
        <div class="studio__finish-body">
          <span class="studio__finish-mark" aria-hidden="true">✓</span>
          <div>
            <h2>這次練習，已有完整紀錄。</h2>
            <p>回到工作台查看商品、流水或交付版本；需要保留時，可以在設定中匯出 SIM JSON。</p>
          </div>
          <button type="button" class="btn btn--primary" @click="goTo('/overview')">回工作總覽</button>
        </div>
      </HudPanel>
    </template>
  </div>
</template>

<style scoped>
.studio {
  display: grid;
  gap: calc(var(--gap) * 1.25);
  min-width: 0;
}
.studio__top {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: flex-end;
  gap: var(--gap);
}
.studio__code {
  margin: 0;
  font-size: 0.7rem;
  letter-spacing: 0.2em;
  color: var(--accent);
}
.studio__kicker {
  margin: 4px 0 0;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  color: var(--ink-dim);
}
.studio__loading,
.studio__notice {
  margin: 0;
  font-size: 0.82rem;
  color: var(--ink-dim);
}
.studio__notice:empty {
  display: none;
}
.studio__error {
  margin: 0;
  color: var(--danger);
  font-size: 0.85rem;
}
.studio__reqs {
  margin: 0;
  padding-left: 1.2em;
  text-align: left;
}
.studio__row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
}
.studio__tools {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
.studio__opening {
  display: grid;
  gap: 4px;
  margin-bottom: var(--gap);
}
.studio__headline {
  margin: 0;
  font-family: var(--font-display);
  font-size: 1.5rem;
  letter-spacing: 0.04em;
}
.studio__intro {
  margin: 0;
  color: var(--ink-dim);
  max-width: 70ch;
}
.studio__theatre-foot {
  margin-top: var(--gap);
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 8px;
  font-size: 0.84rem;
  color: var(--ink-dim);
}
.studio__live {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 0.76rem;
  color: var(--accent);
}
.studio__live i {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--accent);
  animation: live-blink 2s ease-in-out infinite;
}
.studio__live i.is-still {
  animation: none;
}
@keyframes live-blink {
  50% {
    opacity: 0.3;
  }
}
@media (prefers-reduced-motion: reduce) {
  .studio__live i {
    animation: none;
  }
}
.studio__motion {
  margin: 6px 0 0;
  font-size: 0.74rem;
  color: var(--ink-faint);
}
.studio__progress {
  display: grid;
  gap: 6px;
}
.studio__progress-text {
  margin: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
  align-items: center;
  font-size: 0.84rem;
  color: var(--ink-dim);
}
.studio__progress-text strong {
  color: var(--ink);
}
.studio__chapters {
  display: grid;
  gap: var(--gap);
  grid-template-columns: minmax(200px, 260px) minmax(0, 1fr);
  align-items: start;
}
.studio__bottom {
  display: grid;
  gap: var(--gap);
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 320px), 1fr));
  align-items: start;
}
.studio__facts {
  margin: 0;
  display: grid;
  gap: 4px;
}
.studio__facts div {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 3px 0;
  border-bottom: 1px dashed var(--line);
  font-size: 0.84rem;
}
.studio__facts dt {
  color: var(--ink-dim);
}
.studio__facts dd {
  margin: 0;
  text-align: right;
}
.studio__facts-note {
  margin: 8px 0 0;
  font-size: 0.74rem;
  color: var(--ink-faint);
}
.studio__finish-body {
  display: flex;
  flex-wrap: wrap;
  gap: var(--gap);
  align-items: center;
}
.studio__finish-body h2 {
  margin: 0 0 4px;
  font-size: 1.1rem;
}
.studio__finish-body p {
  margin: 0;
  color: var(--ink-dim);
}
.studio__finish-body > div {
  flex: 1 1 260px;
}
.studio__finish-mark {
  width: 48px;
  height: 48px;
  display: grid;
  place-items: center;
  font-size: 1.4rem;
  color: var(--accent-ink);
  background: var(--accent);
  clip-path: polygon(25% 0, 75% 0, 100% 50%, 75% 100%, 25% 100%, 0 50%);
}
.is-compact .studio__intro {
  display: none;
}
@media (max-width: 760px) {
  .studio {
    /* 底部固定操作列的空間 */
    padding-bottom: calc(150px + env(safe-area-inset-bottom));
  }
  .studio__chapters {
    grid-template-columns: minmax(0, 1fr);
  }
  .is-compact .studio__opening,
  .is-compact .studio__diagram,
  .is-compact .studio__motion {
    display: none;
  }
}
</style>
