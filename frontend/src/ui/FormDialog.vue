<script setup lang="ts">
import { computed, reactive, watch } from "vue";
import Dialog from "./Dialog.vue";

export interface FormField {
  name: string;
  label: string;
  /** money：以 SIM 輸入（最多兩位小數），值以原字串送出，由呼叫端換算成 minor。 */
  type?: "text" | "number" | "textarea" | "select" | "date" | "datetime-local" | "email" | "money";
  required?: boolean;
  min?: number;
  max?: number;
  maxlength?: number;
  options?: { value: string; label: string }[];
  hint?: string;
}

/**
 * 一般表單對話框。`blocked` 有值時（例如外觀試看中、上次操作未確認）停用送出並顯示原因。
 * 送出時 emit 欄位值（number 欄位轉成數字，空字串保留給呼叫端決定）。
 * `error` 顯示本地驗證或伺服器錯誤；沒有欄位時顯示「確認執行此模擬操作？」。
 */
const props = withDefaults(
  defineProps<{
    open: boolean;
    title: string;
    fields: FormField[];
    initial?: Record<string, string | number | null>;
    submitLabel?: string;
    busy?: boolean;
    blocked?: string;
    error?: string;
  }>(),
  { initial: () => ({}), submitLabel: "送出", busy: false, blocked: "", error: "" },
);
const emit = defineEmits<{ submit: [values: Record<string, string | number>]; close: [] }>();

const values = reactive<Record<string, string>>({});
const formId = `fd-${Math.random().toString(36).slice(2, 8)}`;

watch(
  () => props.open,
  (open) => {
    if (!open) return;
    for (const f of props.fields) {
      const v = props.initial[f.name];
      values[f.name] = v === null || v === undefined ? "" : String(v);
    }
  },
  { immediate: true },
);

const disabled = computed(() => props.busy || Boolean(props.blocked));

function submit(): void {
  if (disabled.value) return;
  const out: Record<string, string | number> = {};
  for (const f of props.fields) {
    const raw = values[f.name] ?? "";
    out[f.name] = f.type === "number" && raw !== "" ? Number(raw) : raw.trim();
  }
  emit("submit", out);
}
</script>

<template>
  <Dialog :open="open" :title="title" @close="emit('close')">
    <form :id="formId" class="fdlg" novalidate @submit.prevent="submit">
      <p v-if="blocked" class="fdlg__blocked" role="alert">{{ blocked }}</p>
      <p v-if="fields.length === 0" class="fdlg__confirm">確認執行此模擬操作？</p>
      <label v-for="f in fields" :key="f.name" class="field">
        <span class="field__label">{{ f.label }}<span v-if="f.required" class="field__req" aria-hidden="true"> *</span></span>
        <textarea v-if="f.type === 'textarea'" v-model="values[f.name]" :required="f.required" :maxlength="f.maxlength ?? 1000" rows="3" />
        <select v-else-if="f.type === 'select'" v-model="values[f.name]" :required="f.required">
          <option value="">請選擇</option>
          <option v-for="o in f.options ?? []" :key="o.value" :value="o.value">{{ o.label }}</option>
        </select>
        <span v-else-if="f.type === 'money'" class="fdlg__money">
          <input v-model="values[f.name]" type="text" inputmode="decimal" :required="f.required" maxlength="20" class="num" />
          <span class="fdlg__unit num" aria-hidden="true">SIM</span>
        </span>
        <input
          v-else
          v-model="values[f.name]"
          :type="f.type ?? 'text'"
          :required="f.required"
          :min="f.min"
          :max="f.max"
          :maxlength="f.maxlength ?? 1000"
          :class="{ num: f.type === 'number' }"
        />
        <span v-if="f.hint" class="field__hint">{{ f.hint }}</span>
      </label>
      <p v-if="error" class="fdlg__error" role="alert" data-testid="form-error">{{ error }}</p>
    </form>
    <template #footer>
      <button type="button" class="btn btn--ghost" @click="emit('close')">取消</button>
      <button type="submit" class="btn btn--primary" :form="formId" :disabled="disabled">
        {{ busy ? "處理中…" : submitLabel }}
      </button>
    </template>
  </Dialog>
</template>

<style scoped>
.fdlg {
  display: grid;
  gap: var(--gap);
}
.fdlg__blocked {
  margin: 0;
  padding: 8px 10px;
  border-left: 3px solid var(--warn);
  background: color-mix(in srgb, var(--warn) 10%, transparent);
}
.fdlg__confirm {
  margin: 0;
}
.fdlg__error {
  margin: 0;
  padding: 8px 10px;
  border-left: 3px solid var(--danger);
  background: color-mix(in srgb, var(--danger) 10%, transparent);
}
.fdlg__money {
  display: flex;
  align-items: center;
  gap: 8px;
}
.fdlg__money input {
  flex: 1;
}
.fdlg__unit {
  color: var(--ink-dim);
  font-size: 0.8rem;
}
.field__req {
  color: var(--danger);
}
</style>
