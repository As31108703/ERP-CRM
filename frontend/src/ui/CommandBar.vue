<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from "vue";
import { RouterLink, useRouter } from "vue-router";
import { usePreferencesStore, type Density, type SchemePref } from "../stores/preferences";
import { useWorkspaceStore } from "../stores/workspace";
import { ICONS } from "./icons";
import StatusSignal from "./StatusSignal.vue";

/** 頂部指令列：品牌、搜尋、快速新增、外觀設定、SIM 標示與連線訊號。 */
const emit = defineEmits<{ search: []; "quick-create": [] }>();

const store = useWorkspaceStore();
const prefs = usePreferencesStore();
const router = useRouter();

const company = computed(() => store.view?.workspace?.company_name ?? "");
const revision = computed(() => String(store.view?.version ?? 0).padStart(4, "0"));
const quickBlocked = computed(() => store.busy || Boolean(store.pending) || prefs.previewing);
const signal = computed(() =>
  store.error
    ? { tone: "danger" as const, label: "需要處理" }
    : store.pending
      ? { tone: "warn" as const, label: "待確認" }
      : store.busy
        ? { tone: "info" as const, label: "傳輸中" }
        : { tone: "ok" as const, label: "連線正常" },
);

const SCHEME_OPTIONS: { value: SchemePref; label: string }[] = [
  { value: "system", label: "跟隨系統" },
  { value: "light", label: "日間艦橋" },
  { value: "dark", label: "夜間" },
];
const DENSITY_OPTIONS: { value: Density; label: string }[] = [
  { value: "comfortable", label: "舒適" },
  { value: "compact", label: "緊湊" },
];

const open = ref(false);
const popover = ref<HTMLElement | null>(null);
const toggle = ref<HTMLButtonElement | null>(null);

function onDocPointer(event: PointerEvent): void {
  const t = event.target as Node | null;
  if (t && !popover.value?.contains(t) && !toggle.value?.contains(t)) close();
}
function onDocKey(event: KeyboardEvent): void {
  if (event.key === "Escape") {
    close();
    toggle.value?.focus();
  }
}
function openPopover(): void {
  open.value = true;
  document.addEventListener("pointerdown", onDocPointer);
  document.addEventListener("keydown", onDocKey);
}
function close(): void {
  open.value = false;
  document.removeEventListener("pointerdown", onDocPointer);
  document.removeEventListener("keydown", onDocKey);
}
onBeforeUnmount(close);

function browseThemes(): void {
  close();
  void router.push("/design");
}
</script>

<template>
  <header class="cbar">
    <RouterLink :to="store.hasWorkspace ? '/overview' : '/build'" class="cbar__brand" aria-label="星軌 ERP-CRM 首頁">
      <svg class="cbar__logo" viewBox="0 0 32 32" aria-hidden="true">
        <ellipse cx="16" cy="16" rx="14" ry="6" transform="rotate(-24 16 16)" />
        <circle cx="16" cy="16" r="4.5" class="cbar__core" />
        <circle cx="28" cy="10.5" r="1.8" class="cbar__sat" />
      </svg>
      <span class="cbar__name">星軌</span>
      <span class="cbar__suffix num">ERP-CRM</span>
    </RouterLink>

    <div class="cbar__context">
      <span v-if="company" class="cbar__company">{{ company }}</span>
      <span class="cbar__rev num" title="工作區版本">REV {{ revision }}</span>
      <StatusSignal :tone="signal.tone" :label="signal.label" :pulse="store.busy" />
    </div>

    <div class="cbar__actions">
      <button v-if="store.hasWorkspace" type="button" class="btn btn--ghost cbar__search" @click="emit('search')">
        <svg viewBox="0 0 24 24" class="cbar__icon" aria-hidden="true"><path :d="ICONS.search" /></svg>
        <span class="cbar__hide-sm">搜尋工作區</span>
        <kbd class="cbar__hide-sm">Ctrl K</kbd>
      </button>
      <button
        v-if="store.hasWorkspace"
        type="button"
        class="btn btn--primary"
        :disabled="quickBlocked"
        :title="prefs.previewing ? '外觀試看中，請先套用或取消試看' : undefined"
        @click="emit('quick-create')"
      >
        <svg viewBox="0 0 24 24" class="cbar__icon" aria-hidden="true"><path :d="ICONS.plus" /></svg>
        <span class="cbar__hide-sm">快速新增</span>
      </button>
      <div class="cbar__appearance">
        <button
          ref="toggle"
          type="button"
          class="btn btn--ghost"
          :aria-expanded="open"
          aria-haspopup="dialog"
          aria-controls="appearance-popover"
          @click="open ? close() : openPopover()"
        >
          <svg viewBox="0 0 24 24" class="cbar__icon" aria-hidden="true"><path :d="ICONS.appearance" /></svg>
          <span class="cbar__hide-sm">外觀</span>
        </button>
        <div
          v-if="open"
          id="appearance-popover"
          ref="popover"
          class="cbar__popover"
          role="dialog"
          aria-label="外觀設定"
          data-erpcrm-dialog
        >
          <p class="cbar__pop-title">外觀設定</p>
          <div class="field">
            <span class="field__label">配色</span>
            <div class="segmented" role="group" aria-label="配色">
              <button
                v-for="o in SCHEME_OPTIONS"
                :key="o.value"
                type="button"
                :aria-pressed="prefs.scheme === o.value"
                @click="prefs.setScheme(o.value)"
              >
                {{ o.label }}
              </button>
            </div>
          </div>
          <div class="field">
            <span class="field__label">密度</span>
            <div class="segmented" role="group" aria-label="密度">
              <button
                v-for="o in DENSITY_OPTIONS"
                :key="o.value"
                type="button"
                :aria-pressed="prefs.density === o.value"
                @click="prefs.setDensity(o.value)"
              >
                {{ o.label }}
              </button>
            </div>
          </div>
          <p class="cbar__pop-theme">
            目前主題：<strong>{{ prefs.theme.name }}</strong>
            <span v-if="prefs.previewThemeDef" class="badge badge--warn">試看 {{ prefs.previewThemeDef.name }}</span>
          </p>
          <button type="button" class="btn" @click="browseThemes">瀏覽六套主題</button>
          <p v-if="!prefs.persisted" class="cbar__volatile">瀏覽器儲存無法使用，外觀目前只保留在本分頁。</p>
        </div>
      </div>
      <span class="badge badge--accent cbar__sim num" title="所有金額皆為模擬測試幣">SIM<span class="cbar__hide-sm"> 測試幣</span></span>
    </div>
  </header>
</template>

<style scoped>
.cbar {
  display: flex;
  align-items: center;
  gap: var(--gap);
  height: var(--bar-height);
  padding: 0 var(--pad);
  background: color-mix(in srgb, var(--surface) 88%, transparent);
  backdrop-filter: blur(8px);
  border-bottom: 1px solid var(--line);
  box-shadow: 0 1px 0 color-mix(in srgb, var(--accent) 22%, transparent);
  position: relative;
}
.cbar::after {
  content: "";
  position: absolute;
  left: 0;
  right: 0;
  bottom: -1px;
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--accent), transparent);
  opacity: 0.6;
}
.cbar__brand {
  display: flex;
  align-items: center;
  gap: 8px;
  text-decoration: none;
  color: var(--ink);
  flex-shrink: 0;
}
.cbar__logo {
  width: 30px;
  height: 30px;
  fill: none;
  stroke: var(--accent);
  stroke-width: 1.5;
  filter: drop-shadow(0 0 4px var(--glow));
}
.cbar__core {
  fill: var(--accent);
  stroke: none;
}
.cbar__sat {
  fill: var(--accent-2);
  stroke: none;
}
.cbar__name {
  font-family: var(--font-display);
  font-weight: 700;
  font-size: 1.1rem;
  letter-spacing: 0.12em;
}
.cbar__suffix {
  font-size: 0.7rem;
  color: var(--ink-faint);
  letter-spacing: 0.14em;
}
.cbar__context {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  flex: 1;
  padding-left: var(--gap);
  border-left: 1px solid var(--line);
}
.cbar__company {
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.cbar__rev {
  font-size: 0.72rem;
  color: var(--ink-faint);
  letter-spacing: 0.08em;
}
.cbar__actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.cbar__icon {
  width: 16px;
  height: 16px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.cbar__appearance {
  position: relative;
}
.cbar__popover {
  position: absolute;
  right: 0;
  top: calc(100% + 8px);
  z-index: 60;
  width: 280px;
  display: grid;
  gap: 12px;
  padding: var(--pad);
  background: var(--surface);
  border: 1px solid var(--accent);
  box-shadow: 0 0 24px var(--glow);
  clip-path: polygon(0 0, calc(100% - 12px) 0, 100% 12px, 100% 100%, 12px 100%, 0 calc(100% - 12px));
}
.cbar__pop-title {
  margin: 0;
  font-family: var(--font-display);
  letter-spacing: 0.08em;
}
.cbar__pop-theme {
  margin: 0;
  font-size: 0.85rem;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}
.cbar__volatile {
  margin: 0;
  font-size: 0.75rem;
  color: var(--warn);
}
@media (max-width: 959.98px) {
  .cbar__rev {
    display: none;
  }
}
@media (max-width: 759.98px) {
  .cbar__hide-sm,
  .cbar__suffix {
    display: none;
  }
  .cbar__context {
    border-left: 0;
    padding-left: 0;
  }
  .cbar__popover {
    position: fixed;
    left: 16px;
    right: 16px;
    top: calc(var(--bar-height) + 8px);
    width: auto;
  }
}
</style>
