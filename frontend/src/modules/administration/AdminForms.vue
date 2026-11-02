<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import { useWorkspaceStore } from "../../stores/workspace";
import Dialog from "../../ui/Dialog.vue";
import type { AdminCommand, AdminField, AdminFormSpec, AdminValues } from "./adminForms";

/**
 * 行政表單對話框（A§5「Dialog behaviour」）：
 * - 欄位可依其他欄位顯示或隱藏、選項可連動（例如組織 → 假員工）。
 * - 送出前執行表單的前端預檢，錯誤顯示在表單內，不送出。
 * - 處理中不可關閉；上次操作結果未確認或外觀試看中時顯示原因並停用送出。
 * 通過預檢後 emit `submit(command)`，由工作台送出並決定成功後的定位。
 */
const props = withDefaults(defineProps<{ spec: AdminFormSpec | null; error?: string }>(), { error: "" });
const emit = defineEmits<{ submit: [command: AdminCommand]; close: [] }>();

const store = useWorkspaceStore();
const values = reactive<AdminValues>({});
const localError = ref("");
const formId = `adm-${Math.random().toString(36).slice(2, 8)}`;

watch(
  () => props.spec,
  (spec) => {
    for (const key of Object.keys(values)) delete values[key];
    localError.value = "";
    if (!spec) return;
    for (const f of spec.fields) values[f.name] = spec.initial[f.name] ?? (f.type === "checkbox" ? false : "");
  },
  { immediate: true },
);

const blocked = computed(() => store.formBlockedReason);

const shown = computed(() => (props.spec?.fields ?? []).filter((f) => (f.show ? f.show(values) : true)));
const shownError = computed(() => localError.value || props.error);

function options(field: AdminField) {
  return field.options ? field.options(values) : [];
}

function changed(name: string): void {
  props.spec?.onChange?.(name, values);
}

function onInput(field: AdminField, event: Event): void {
  const el = event.target as HTMLInputElement;
  values[field.name] = field.type === "checkbox" ? el.checked : el.value;
  if (field.type === "select" || field.type === "checkbox") changed(field.name);
}

function close(): void {
  if (store.busy) return;
  emit("close");
}

function submit(): void {
  const spec = props.spec;
  if (!spec || store.busy || blocked.value) return;
  const out = spec.build({ ...values });
  if (typeof out === "string") {
    localError.value = out;
    return;
  }
  localError.value = "";
  emit("submit", out);
}

function inputType(field: AdminField): string {
  if (field.type === "datetime") return "datetime-local";
  if (field.type === "money") return "text";
  return field.type;
}
</script>

<template>
  <Dialog :open="spec !== null" :title="spec?.title ?? ''" :code="spec?.code ?? ''" @close="close">
    <form v-if="spec" :id="formId" class="afrm" novalidate data-testid="admin-form" @submit.prevent="submit">
      <p v-if="blocked" class="afrm__blocked" role="alert">{{ blocked }}</p>
      <p v-if="spec.note" class="afrm__note">{{ spec.note }}</p>
      <p v-if="spec.fields.length === 0 && !spec.note" class="afrm__note">確認執行此模擬操作？</p>

      <template v-for="f in shown" :key="f.name">
        <label v-if="f.type === 'checkbox'" class="afrm__check">
          <input type="checkbox" :name="f.name" :checked="values[f.name] === true" :disabled="Boolean(blocked)" @change="onInput(f, $event)" />
          <span>{{ f.label }}</span>
        </label>
        <label v-else class="field">
          <span class="field__label">{{ f.label }}<span v-if="f.required" class="afrm__req" aria-hidden="true"> *</span></span>
          <textarea
            v-if="f.type === 'textarea'"
            :name="f.name"
            :value="String(values[f.name] ?? '')"
            :maxlength="f.maxlength ?? 1000"
            :disabled="Boolean(blocked)"
            rows="3"
            @input="onInput(f, $event)"
          />
          <select
            v-else-if="f.type === 'select'"
            :name="f.name"
            :value="String(values[f.name] ?? '')"
            :disabled="Boolean(blocked)"
            @change="onInput(f, $event)"
          >
            <option value="">{{ f.emptyLabel ?? "請選擇" }}</option>
            <option v-for="o in options(f)" :key="o.value" :value="o.value">{{ o.label }}</option>
          </select>
          <span v-else-if="f.type === 'money'" class="afrm__money">
            <input
              :name="f.name"
              :value="String(values[f.name] ?? '')"
              type="text"
              inputmode="decimal"
              maxlength="20"
              class="num"
              :disabled="Boolean(blocked)"
              @input="onInput(f, $event)"
            />
            <span class="afrm__unit num" aria-hidden="true">SIM</span>
          </span>
          <input
            v-else
            :name="f.name"
            :value="String(values[f.name] ?? '')"
            :type="inputType(f)"
            :min="f.min"
            :max="f.max"
            :maxlength="f.type === 'text' ? f.maxlength : undefined"
            :class="{ num: f.type !== 'text' }"
            :disabled="Boolean(blocked)"
            @input="onInput(f, $event)"
          />
          <span v-if="f.hint" class="field__hint">{{ f.hint }}</span>
        </label>
      </template>

      <p v-if="shownError" class="afrm__error" role="alert" data-testid="form-error">{{ shownError }}</p>
    </form>
    <template #footer>
      <button type="button" class="btn btn--ghost" :disabled="store.busy" @click="close">取消</button>
      <button
        type="submit"
        class="btn"
        :class="spec?.danger ? 'btn--danger' : 'btn--primary'"
        :form="formId"
        :disabled="store.busy || Boolean(blocked)"
        data-testid="admin-form-submit"
      >
        {{ store.busy ? "處理中…" : spec?.submitLabel ?? "送出" }}
      </button>
    </template>
  </Dialog>
</template>

<style scoped>
.afrm {
  display: grid;
  gap: var(--gap);
}
.afrm__blocked {
  margin: 0;
  padding: 8px 10px;
  border-left: 3px solid var(--warn);
  background: color-mix(in srgb, var(--warn) 10%, transparent);
}
.afrm__note {
  margin: 0;
  color: var(--ink-dim);
  font-size: 0.88rem;
}
.afrm__error {
  margin: 0;
  padding: 8px 10px;
  border-left: 3px solid var(--danger);
  background: color-mix(in srgb, var(--danger) 10%, transparent);
}
.afrm__check {
  display: flex;
  align-items: center;
  gap: 8px;
}
.afrm__money {
  display: flex;
  align-items: center;
  gap: 8px;
}
.afrm__money input {
  flex: 1;
}
.afrm__unit {
  color: var(--ink-dim);
  font-size: 0.8rem;
}
.afrm__req {
  color: var(--danger);
}
</style>
