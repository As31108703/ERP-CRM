<script setup lang="ts">
import { useWorkspaceStore } from "../../stores/workspace";
import FormDialog from "../../ui/FormDialog.vue";
import type { useCommandForm } from "./commandForm";

/** 把 useCommandForm 的狀態接到 FormDialog（各模組頁共用）；外觀試看中或上次操作未確認時停用送出。 */
defineProps<{ form: ReturnType<typeof useCommandForm> }>();
const store = useWorkspaceStore();
</script>

<template>
  <FormDialog
    :open="form.spec.value !== null"
    :title="form.spec.value?.title ?? ''"
    :fields="form.spec.value?.fields ?? []"
    :initial="form.spec.value?.initial"
    :submit-label="form.spec.value?.submitLabel ?? '確認模擬操作'"
    :busy="store.busy"
    :blocked="store.formBlockedReason"
    :error="form.error.value"
    @submit="form.submit"
    @close="form.close"
  />
</template>
