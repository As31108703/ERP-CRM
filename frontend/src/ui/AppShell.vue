<script setup lang="ts">
import { computed, watchEffect } from "vue";
import { useRoute } from "vue-router";
import { usePreferencesStore } from "../stores/preferences";
import { useWorkspaceStore } from "../stores/workspace";
import CommandBar from "./CommandBar.vue";
import GlobalLoadingBar from "./GlobalLoadingBar.vue";
import NavRail from "./NavRail.vue";

/**
 * 外殼版面：頂部指令列、左側艦橋導覽軌（760px 以下成為底部列）、主區。
 * 主題試看期間顯示試看列，提醒資料操作已暫停。
 */
const emit = defineEmits<{ search: []; "quick-create": [] }>();

const store = useWorkspaceStore();
const prefs = usePreferencesStore();
const route = useRoute();

const preview = computed(() => prefs.previewThemeDef);

watchEffect(() => {
  const ws = store.view?.workspace;
  const page = typeof route.meta.title === "string" ? route.meta.title : "";
  const head = ws?.company_name || page || "星軌 ERP-CRM";
  document.title = `${head}｜${store.view?.expires_at ? "公開 SIM 試用" : "SIM 自架工作台"}`;
});
</script>

<template>
  <div class="shell" :class="store.hasWorkspace ? 'app-layout' : 'welcome-layout'">
    <a class="shell__skip" href="#main">跳到主要內容</a>
    <GlobalLoadingBar />
    <CommandBar class="shell__bar" @search="emit('search')" @quick-create="emit('quick-create')" />
    <NavRail class="shell__rail" />
    <main id="main" class="shell__main" tabindex="-1">
      <div v-if="preview" class="shell__preview" role="status" data-testid="design-preview-bar">
        <span class="shell__preview-tag num">PREVIEW</span>
        <span>正在試看「{{ preview.name }}」，資料操作已暫停。按 <kbd>Esc</kbd> 可取消。</span>
        <span class="shell__preview-actions">
          <button type="button" class="btn btn--ghost btn--sm" @click="prefs.cancelPreview()">取消試看</button>
          <button type="button" class="btn btn--primary btn--sm" @click="prefs.applyTheme(preview.id)">套用這個主題</button>
        </span>
      </div>
      <div class="shell__notices"><slot name="notices" /></div>
      <slot />
    </main>
  </div>
</template>

<style scoped>
.shell {
  display: grid;
  grid-template-columns: var(--rail-width) minmax(0, 1fr);
  grid-template-rows: var(--bar-height) minmax(0, 1fr);
  grid-template-areas:
    "bar bar"
    "rail main";
  height: 100dvh;
}
.shell__bar {
  grid-area: bar;
  z-index: 20;
}
.shell__rail {
  grid-area: rail;
  z-index: 10;
}
.shell__main {
  grid-area: main;
  overflow-y: auto;
  padding: calc(var(--pad) * 1.25);
  outline: none;
  scroll-padding-top: var(--pad);
}
.shell__skip {
  position: absolute;
  left: -999px;
  top: 8px;
  z-index: 200;
  padding: 6px 12px;
  background: var(--accent);
  color: var(--accent-ink);
}
.shell__skip:focus {
  left: 8px;
}
.shell__preview {
  position: sticky;
  top: calc(var(--pad) * -1.25);
  z-index: 15;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
  margin: calc(var(--pad) * -1.25) calc(var(--pad) * -1.25) var(--pad);
  padding: 8px calc(var(--pad) * 1.25);
  background: repeating-linear-gradient(
      -45deg,
      color-mix(in srgb, var(--accent-2) 14%, transparent) 0 10px,
      transparent 10px 20px
    ),
    var(--surface);
  border-bottom: 1px solid var(--accent-2);
}
.shell__preview-tag {
  font-size: 0.7rem;
  letter-spacing: 0.2em;
  color: var(--accent-2);
}
.shell__preview-actions {
  margin-left: auto;
  display: flex;
  gap: 8px;
}
.shell__notices {
  display: grid;
  gap: 8px;
  margin-bottom: var(--gap);
}
.shell__notices:empty {
  display: none;
}

@media (max-width: 759.98px) {
  .shell {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: var(--bar-height) minmax(0, 1fr) auto;
    grid-template-areas:
      "bar"
      "main"
      "rail";
  }
  .shell__main {
    padding: 16px;
  }
  .shell__preview {
    top: -16px;
    margin: -16px -16px 16px;
    padding: 8px 16px;
  }
}
</style>
