<script setup lang="ts">
import { computed, ref } from "vue";
import { useRouter } from "vue-router";
import { formatDateTime } from "../../lib/format";
import { moduleLabel } from "../../lib/modules";
import { list, num, str } from "../../lib/records";
import { useWorkspaceStore } from "../../stores/workspace";
import Dialog from "../../ui/Dialog.vue";
import HudPanel from "../../ui/HudPanel.vue";
import { downloadFile } from "../../lib/download";
import type { BuildConfig } from "../../lib/modules";
import CustomSetup from "../build/CustomSetup.vue";
import { switchLocation } from "../build/draft";
import { retentionSummary } from "../build/useBuilder";
import PageHead from "../shared/PageHead.vue";
import BackupRestoreDialog from "./BackupRestoreDialog.vue";
import { BACKUP_FILENAME, EXPORT_PATH, EXPORTED_MESSAGE, precheckBackup, type BackupCandidate } from "./backup";

const CLEAR_PATH = "/api/v1/workspace/clear";

const store = useWorkspaceStore();
const router = useRouter();

const ws = computed(() => store.view?.workspace ?? null);
const blocked = computed(() => store.blockedReason());

const industryName = computed(() => {
  const id = ws.value?.industry ?? "";
  return store.templates?.items.find((t) => t.id === id)?.name ?? id;
});
const moduleNames = computed(() => (ws.value?.modules ?? []).map(moduleLabel).join("、") || "（無）");
const retention = computed(() => retentionSummary(store));
const modeText = computed(() =>
  store.templates?.defaults.public_demo ? "公開試用 · SIM 測試幣，不連真實銀行與金流" : "自架模擬 · SIM 測試幣，不連真實銀行與金流",
);
const meta = computed(() =>
  JSON.stringify(
    { generation_id: ws.value?.generation_id, version: ws.value?.version, schema_version: ws.value?.schema_version ?? null },
    null,
    2,
  ),
);

/** 操作歷史：版本號新到舊（歷史列不一定帶 id，不以 id 篩選）。 */
const history = computed(() =>
  list(ws.value ?? undefined, "history")
    .slice()
    .sort((a, b) => num(b, "version") - num(a, "version") || str(b, "created_at").localeCompare(str(a, "created_at"))),
);

// ── 匯入 ──
const fileInput = ref<HTMLInputElement | null>(null);
const importError = ref("");
const checkingFile = ref(false);
const candidate = ref<BackupCandidate | null>(null);

function pickFile(): void {
  importError.value = "";
  if (blocked.value) {
    importError.value = blocked.value;
    return;
  }
  fileInput.value?.click();
}

async function onFile(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  importError.value = "";
  if (!file) return;
  if (blocked.value) {
    importError.value = blocked.value;
    return;
  }
  checkingFile.value = true;
  try {
    const result = await precheckBackup(file);
    if (result.ok) candidate.value = result.candidate;
    else importError.value = result.error;
  } finally {
    checkingFile.value = false;
    // 允許再次選同一個檔案
    try {
      input.value = "";
    } catch {
      // 部分環境不允許重設 file input，略過
    }
  }
}

// ── 匯出 ──
const exporting = ref(false);
const exportError = ref("");
const exportMessage = ref("");

async function exportBackup(): Promise<void> {
  if (exporting.value) return;
  exporting.value = true;
  exportError.value = "";
  exportMessage.value = "";
  try {
    const error = await downloadFile(EXPORT_PATH, BACKUP_FILENAME);
    if (error) exportError.value = error;
    else exportMessage.value = EXPORTED_MESSAGE;
  } finally {
    exporting.value = false;
  }
}

// ── 清除與切換範本 ──
const switching = ref(false);
const clearMode = ref<"clear" | "switch" | null>(null);
let switchTarget: BuildConfig | null = null;

function startSwitch(): void {
  switching.value = true;
}

function requestSwitch(config: BuildConfig): void {
  switchTarget = { ...config, modules: [...config.modules] };
  clearMode.value = "switch";
}

async function confirmClear(): Promise<void> {
  const mode = clearMode.value;
  if (!mode || store.busy) return;
  const result = await store.run("POST", CLEAR_PATH, {});
  if (result === null) return;
  clearMode.value = null;
  // 單純清除回到快速上手；切換範本則帶著選好的範本前往自訂建置（沒有工作區時設定頁不可停留）
  if (mode === "switch" && switchTarget) await router.push(switchLocation(switchTarget));
  else await router.push("/build");
}
</script>

<template>
  <div class="mpage" data-testid="page-settings">
    <PageHead code="SYSTEM · SETTINGS · DATA" title="設定與資料" lead="匯出或還原 SIM 備份、切換產業範本、清除測試資料，並查看每一次模擬操作的紀錄。" />

    <div v-if="ws" class="mpage__grid">
      <HudPanel title="工作區資訊" code="SYS-01">
        <dl class="set__info">
          <div><dt>產業範本</dt><dd>{{ industryName }}</dd></div>
          <div><dt>啟用模組</dt><dd>{{ moduleNames }}</dd></div>
          <div><dt>資料保留</dt><dd>{{ retention }}</dd></div>
          <div><dt>模式</dt><dd>{{ modeText }}</dd></div>
        </dl>
        <details class="mpage__expander">
          <summary>資料世代與版本</summary>
          <pre class="set__json num">{{ meta }}</pre>
        </details>
      </HudPanel>

      <HudPanel title="備份與資料" code="BKP-02">
        <div class="set__actions">
          <button type="button" class="btn btn--primary" data-testid="export-backup" :disabled="exporting" @click="exportBackup">
            {{ exporting ? "匯出中…" : "匯出 SIM JSON" }}
          </button>
          <button type="button" class="btn" :disabled="Boolean(blocked) || checkingFile" @click="pickFile">
            {{ checkingFile ? "檢查檔案中…" : "匯入 SIM JSON" }}
          </button>
          <input
            ref="fileInput"
            class="set__file"
            type="file"
            accept="application/json,.json"
            data-testid="import-file"
            aria-label="選擇 SIM JSON 備份檔"
            tabindex="-1"
            @change="onFile"
          />
          <button type="button" class="btn" :disabled="Boolean(blocked)" @click="startSwitch">切換產業範本</button>
          <button
            type="button"
            class="btn btn--danger"
            data-testid="clear-workspace"
            :disabled="Boolean(blocked)"
            @click="clearMode = 'clear'"
          >
            清除測試資料
          </button>
        </div>
        <p v-if="blocked" class="set__note">{{ blocked }}</p>
        <p v-if="exportMessage" class="set__ok" role="status" data-testid="export-message">{{ exportMessage }}</p>
        <p v-if="exportError" class="set__error" role="alert" data-testid="export-error">{{ exportError }}</p>
        <p v-if="importError" class="set__error" role="alert" data-testid="import-error">{{ importError }}</p>
        <p class="set__note">
          備份一次上傳完成：檔案上限 8 MiB，精簡後內容上限 3 MiB。還原前會先在瀏覽器檢查格式，再由伺服器完整驗證；驗證不通過時現有資料不變。
        </p>
      </HudPanel>

      <HudPanel title="模擬操作歷史" code="LOG-03">
        <ol v-if="history.length" class="set__history" data-testid="history">
          <li v-for="(h, i) in history" :key="`${num(h, 'version')}-${i}`">
            <span class="num set__action">{{ str(h, "action") }}</span>
            <span class="mpage__dim">v{{ num(h, "version") }} · {{ formatDateTime(h.created_at) }}</span>
          </li>
        </ol>
        <p v-else class="mpage__dim" data-testid="history">尚未進行模擬操作。</p>
      </HudPanel>
    </div>

    <CustomSetup v-if="switching && ws" @request-clear="requestSwitch" />

    <Dialog :open="clearMode !== null" :title="clearMode === 'switch' ? '清除後切換範本' : '清除測試資料'" code="WIPE" @close="clearMode = null">
      <p class="set__warn">
        清除後，目前工作區的商品、訂單、錢包、紀錄與操作歷史都會刪除，無法復原。需要保留請先匯出 SIM JSON 備份。
      </p>
      <p v-if="store.error && clearMode" class="set__error" role="alert">{{ store.error }}</p>
      <template #footer>
        <button type="button" class="btn btn--ghost" @click="clearMode = null">取消</button>
        <button type="button" class="btn btn--danger" :disabled="store.busy" @click="confirmClear">
          {{ store.busy ? "處理中…" : "確認清除" }}
        </button>
      </template>
    </Dialog>

    <BackupRestoreDialog :candidate="candidate" @close="candidate = null" />
  </div>
</template>

<style scoped src="../shared/page.css"></style>
<style scoped>
.set__info {
  display: grid;
  gap: 8px;
  margin: 0 0 var(--gap);
}
.set__info dt {
  font-size: 0.72rem;
  letter-spacing: 0.08em;
  color: var(--ink-dim);
}
.set__info dd {
  margin: 0;
}
.set__json {
  margin: 6px 0 0;
  font-size: 0.8rem;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.set__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.set__file {
  position: absolute;
  width: 1px;
  height: 1px;
  opacity: 0;
  pointer-events: none;
}
.set__note {
  margin: 10px 0 0;
  font-size: 0.85rem;
  color: var(--ink-dim);
}
.set__ok {
  margin: 10px 0 0;
  color: var(--ok);
}
.set__error {
  margin: 10px 0 0;
  color: var(--danger);
}
.set__warn {
  margin: 0;
  color: var(--warn);
}
.set__history {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 4px;
  max-height: 420px;
  overflow-y: auto;
}
.set__history li {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 4px 12px;
  padding: 4px 8px;
  border-left: 2px solid var(--line-strong);
}
.set__action {
  overflow-wrap: anywhere;
}
</style>
