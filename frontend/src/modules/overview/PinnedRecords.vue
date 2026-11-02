<script setup lang="ts">
import { computed } from "vue";
import type { TargetRef } from "../../api/types";
import { findRow, isRecordKind, RECORD_KINDS, recordName, statusKey, statusLabel } from "../../lib/records";
import { moduleLabel } from "../../lib/modules";
import { PIN_LIMIT, useUiStore } from "../../stores/ui";
import { useWorkspaceStore } from "../../stores/workspace";
import HudPanel from "../../ui/HudPanel.vue";

/** 總覽的釘選紀錄：卡片內容依目前快照重建，點選前往紀錄，可取消釘選。 */
const ui = useUiStore();
const store = useWorkspaceStore();

interface PinEntry {
  target: TargetRef;
  title: string;
  description: string;
  status: string;
}

const entries = computed<PinEntry[]>(() => {
  const ws = store.view?.workspace;
  return ui.pins.flatMap((target) => {
    if (!isRecordKind(target.kind)) return [];
    const def = RECORD_KINDS[target.kind];
    const row = findRow(ws, def.collection, target.id);
    if (!row) return [];
    const hasStatus = target.kind === "product" || target.kind === "wallet" || typeof row.status === "string";
    return [
      {
        target,
        title: recordName(row, def.label),
        description: def.label,
        status: hasStatus ? statusLabel(statusKey(target.kind, row)) : moduleLabel(target.module),
      },
    ];
  });
});
</script>

<template>
  <HudPanel title="釘選紀錄" code="PIN-DOCK" eyebrow="自己的工作入口 · 只保存在本分頁" data-testid="pinned-records">
    <template #actions>
      <span class="badge num" data-testid="pinned-count">{{ entries.length }}／{{ PIN_LIMIT }}</span>
    </template>
    <ul v-if="entries.length" class="ov-grid">
      <li
        v-for="e in entries"
        :key="`${e.target.kind}:${e.target.id}`"
        class="pin"
        data-testid="pinned-record"
        :data-record-id="e.target.id"
        :data-record-kind="e.target.kind"
      >
        <button type="button" class="ov-tile" data-testid="pinned-open" @click="ui.navigateTo(e.target)">
          <span class="ov-tile__title">{{ e.title }}</span>
          <span class="ov-tile__text">{{ e.description }}</span>
          <span class="ov-tile__meta">{{ e.status }} ↗</span>
        </button>
        <button
          type="button"
          class="pin__remove"
          data-testid="pinned-remove"
          :aria-label="`取消釘選：${e.title}`"
          @click="ui.togglePin(e.target)"
        >
          ×
        </button>
      </li>
    </ul>
    <p v-else class="ov-empty">在紀錄卡片按「釘選」，把常用的客戶、訂單或任務放在這裡。入口只指向目前工作區裡仍存在的紀錄。</p>
  </HudPanel>
</template>

<style scoped src="./overview.css"></style>
<style scoped>
.pin {
  position: relative;
}
.pin .ov-tile {
  padding-right: 36px;
}
.pin__remove {
  position: absolute;
  top: 6px;
  right: 6px;
  width: 26px;
  height: 26px;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--ink-dim);
  cursor: pointer;
}
.pin__remove:hover {
  color: var(--danger);
  border-color: var(--danger);
}
</style>
