<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { useWorkspaceStore } from "../../stores/workspace";
import Dialog from "../../ui/Dialog.vue";
import ProgressBar from "../../ui/ProgressBar.vue";
import StepProgress from "../../ui/StepProgress.vue";
import { IMPORT_PATH, RESTORE_STEPS, RESTORED_MESSAGE, type BackupCandidate, type RestorePhase } from "./backup";

/**
 * 還原確認與進度：先顯示備份摘要，確認後以 XHR 上傳，依序經過
 * 檢查 → 上傳中（百分比）→ 伺服器驗證中 → 完成。傳輸中不可關閉。
 */
const props = defineProps<{ candidate: BackupCandidate | null }>();
const emit = defineEmits<{ close: [] }>();

const store = useWorkspaceStore();
const phase = ref<RestorePhase>("confirm");
const failedPhase = ref<RestorePhase | null>(null);
const loaded = ref(0);
const total = ref(0);
const error = ref("");

watch(
  () => props.candidate,
  () => {
    phase.value = "confirm";
    failedPhase.value = null;
    loaded.value = 0;
    total.value = 0;
    error.value = "";
  },
);

const running = computed(() => ["checking", "uploading", "verifying"].includes(phase.value));
const stepIndex = computed(() => {
  const at = failedPhase.value ?? phase.value;
  if (at === "done") return RESTORE_STEPS.length;
  return Math.max(0, RESTORE_STEPS.findIndex((s) => s.phase === at));
});
const percent = computed(() => (total.value > 0 ? Math.round((loaded.value / total.value) * 100) : 0));
const barLabel = computed(() => {
  if (phase.value === "uploading") return `上傳中 · ${percent.value}%`;
  if (phase.value === "failed") return "還原未完成";
  return RESTORE_STEPS.find((s) => s.phase === phase.value)?.label ?? "";
});
const sizeKiB = computed(() => (props.candidate ? (props.candidate.bytes / 1024).toFixed(1) : "0"));

function close(): void {
  if (running.value) return;
  emit("close");
}

function fail(at: RestorePhase, message: string): void {
  failedPhase.value = at;
  phase.value = "failed";
  error.value = message;
}

async function confirm(): Promise<void> {
  const candidate = props.candidate;
  if (!candidate || phase.value !== "confirm") return;
  phase.value = "checking";
  error.value = "";
  const blocked = store.blockedReason();
  if (blocked) {
    fail("checking", blocked);
    return;
  }
  // 讓「檢查」階段先呈現在畫面上，再開始傳送
  await nextTick();
  const call = store.upload(
    IMPORT_PATH,
    candidate.payload,
    {
      onProgress: (l, t) => {
        if (phase.value !== "uploading") return;
        loaded.value = l;
        total.value = t;
      },
      onUploaded: () => {
        if (phase.value !== "uploading") return;
        loaded.value = total.value;
        phase.value = "verifying";
      },
    },
    RESTORED_MESSAGE,
  );
  if (phase.value === "checking") phase.value = "uploading";
  const result = await call;
  if (result === null) {
    fail(phase.value === "uploading" ? "uploading" : "verifying", store.error || "還原未完成，現有資料保留。");
    return;
  }
  phase.value = "done";
}
</script>

<template>
  <Dialog :open="candidate !== null" title="還原 SIM 備份" code="RESTORE · BKP" @close="close">
    <div v-if="candidate" class="rst" :data-backup-phase="phase">
      <dl class="rst__facts">
        <div><dt>檔名</dt><dd>{{ candidate.fileName }}</dd></div>
        <div><dt>公司名稱</dt><dd>{{ candidate.companyName || "（未提供）" }}</dd></div>
        <div><dt>大小</dt><dd class="num">{{ sizeKiB }} KiB</dd></div>
        <div><dt>模組數</dt><dd class="num">{{ candidate.moduleCount }}</dd></div>
        <div><dt>模式</dt><dd>SIM 模擬資料，不含真實金流</dd></div>
      </dl>
      <p class="rst__warn">
        還原會以備份內容建立新的資料世代並取代目前的工作區；舊的教學進度與釘選不會帶過去。伺服器驗證不通過時，現有資料完全保留。
      </p>

      <template v-if="phase !== 'confirm'">
        <StepProgress
          label="還原進度"
          :steps="RESTORE_STEPS.map((s) => s.label)"
          :current="stepIndex"
          :failed-at="failedPhase ? stepIndex : null"
        />
        <ProgressBar
          :label="barLabel"
          :value="phase === 'done' ? 100 : percent"
          :max="100"
          :indeterminate="phase === 'checking' || phase === 'verifying'"
          :tone="phase === 'failed' ? 'danger' : phase === 'done' ? 'ok' : 'accent'"
        />
        <p v-if="phase === 'done'" class="rst__ok" role="status">{{ RESTORED_MESSAGE }}</p>
        <p v-if="error" class="rst__error" role="alert">{{ error }}</p>
      </template>
    </div>
    <template #footer>
      <template v-if="phase === 'confirm'">
        <button type="button" class="btn btn--ghost" @click="close">取消，保留現在資料</button>
        <button type="button" class="btn btn--primary" @click="confirm">確認還原模擬資料</button>
      </template>
      <button v-else type="button" class="btn" :disabled="running" @click="close">
        {{ running ? "處理中…" : "關閉" }}
      </button>
    </template>
  </Dialog>
</template>

<style scoped>
.rst {
  display: grid;
  gap: var(--gap);
}
.rst__facts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 8px;
  margin: 0;
}
.rst__facts dt {
  font-size: 0.72rem;
  letter-spacing: 0.08em;
  color: var(--ink-dim);
}
.rst__facts dd {
  margin: 0;
  overflow-wrap: anywhere;
}
.rst__warn {
  margin: 0;
  color: var(--warn);
  font-size: 0.9rem;
}
.rst__ok {
  margin: 0;
  color: var(--ok);
}
.rst__error {
  margin: 0;
  color: var(--danger);
}
</style>
