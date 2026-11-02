<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { moduleLabel } from "../../lib/modules";
import { useUiStore } from "../../stores/ui";
import { useWorkspaceStore } from "../../stores/workspace";
import Dialog from "../../ui/Dialog.vue";
import { useCommandForm } from "../shared/commandForm";
import CommandDialog from "../shared/CommandDialog.vue";
import { CREATE_KINDS, CREATE_MODULE, CREATE_NAMES, createBlocker, createSpec, type CreateKind } from "../shared/createForms";

/**
 * 快速新增（F§2）：八種紀錄。條件不足時按鈕停用並寫出原因；選定後關閉選單、開啟對應的新增表單。
 * 送出前不會建立任何資料。
 */
const ui = useUiStore();
const store = useWorkspaceStore();
const form = useCommandForm();

const ws = computed(() => store.view?.workspace ?? null);
const open = computed(() => ui.quickCreateOpen && ws.value !== null && form.spec.value === null);
const choices = computed(() =>
  CREATE_KINDS.map((kind) => ({
    kind,
    name: CREATE_NAMES[kind],
    module: CREATE_MODULE[kind],
    reason: createBlocker(kind, ws.value),
  })),
);

const list = ref<HTMLElement | null>(null);

/** 開啟時聚焦第一個可用的項目（Dialog 預設會先聚焦關閉鈕，這裡在其後覆寫）。 */
watch(
  open,
  async (isOpen) => {
    if (!isOpen) return;
    await nextTick();
    list.value?.querySelector<HTMLButtonElement>("button:not([disabled])")?.focus();
  },
  { flush: "post" },
);

function choose(kind: CreateKind): void {
  const reason = createBlocker(kind, ws.value);
  if (reason) {
    store.error = `${CREATE_NAMES[kind]}尚未就緒：${reason}。`;
    return;
  }
  const blocked = store.blockedReason();
  if (blocked) {
    store.error = blocked;
    return;
  }
  ui.closeQuickCreate();
  ui.closeSearch();
  form.open(createSpec(kind, ws.value));
}
</script>

<template>
  <Dialog :open="open" title="快速新增" code="QCK-FAB" wide @close="ui.closeQuickCreate()">
    <div data-testid="quick-create-dialog">
      <p class="qc__lead">選擇項目後會開啟表單，確認送出前不會新增資料。</p>
      <ul ref="list" class="ov-grid">
        <li v-for="c in choices" :key="c.kind">
          <button
            type="button"
            class="ov-tile"
            :data-testid="`quick-create-${c.kind}`"
            :disabled="Boolean(c.reason)"
            @click="choose(c.kind)"
          >
            <span class="ov-tile__title">{{ c.name }}</span>
            <span class="ov-tile__text" :class="{ 'qc__reason': c.reason }">{{ c.reason ?? `${moduleLabel(c.module)} · 開啟新增表單` }}</span>
          </button>
        </li>
      </ul>
      <p class="ov-note">目前工作區：{{ ws?.company_name }}。未啟用的模組或缺少的前置資料會先列出原因。</p>
    </div>
  </Dialog>
  <CommandDialog :form="form" />
</template>

<style scoped src="./overview.css"></style>
<style scoped>
.qc__lead {
  margin: 0 0 12px;
  color: var(--ink-dim);
}
.qc__reason {
  color: var(--warn);
}
</style>
