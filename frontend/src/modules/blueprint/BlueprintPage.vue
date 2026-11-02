<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import HudPanel from "../../ui/HudPanel.vue";
import StatusSignal from "../../ui/StatusSignal.vue";
import { BLUEPRINT, BLUEPRINT_PHASES, blueprintTitle, type BlueprintItem } from "./blueprint";

const route = useRoute();
const phase = ref(0);

const shown = computed(() => BLUEPRINT.filter((b) => phase.value === 0 || b.phase === phase.value));
const byPhase = computed(() =>
  BLUEPRINT_PHASES.map((p) => ({ ...p, items: shown.value.filter((b) => b.phase === p.phase) })).filter(
    (p) => p.items.length > 0,
  ),
);
const focus = computed(() => (typeof route.query.focus === "string" ? route.query.focus : ""));

function dependencyText(item: BlueprintItem): string {
  return item.dependsOn.map((d) => (BLUEPRINT.some((b) => b.id === d) ? blueprintTitle(d) : d)).join("、");
}

onMounted(async () => {
  if (!focus.value) return;
  await nextTick();
  const el = document.getElementById(`bp-${focus.value}`);
  if (el) {
    el.scrollIntoView?.({ block: "start" });
    el.focus?.({ preventScroll: true });
  }
});
</script>

<template>
  <div class="blueprint" data-testid="page-blueprint">
    <header class="blueprint__head">
      <p class="blueprint__eyebrow num">EXPANSION BLUEPRINT · 07</p>
      <h1 class="blueprint__title">企業擴充藍圖</h1>
      <p class="blueprint__lead">
        這一頁說明星軌 ERP-CRM 之後打算加入的企業模組：它們要解決什麼問題、怎麼操作、排在哪一期。這些都還是規劃，頁面上不會建立任何資料。
      </p>
      <StatusSignal tone="warn" label="規劃中・尚未實作" />
    </header>

    <div class="blueprint__phases" role="group" aria-label="依分期篩選">
      <button type="button" class="btn btn--sm" :aria-pressed="phase === 0" @click="phase = 0">全部分期</button>
      <button
        v-for="p in BLUEPRINT_PHASES"
        :key="p.phase"
        type="button"
        class="btn btn--sm"
        :aria-pressed="phase === p.phase"
        :data-phase="p.phase"
        @click="phase = p.phase"
      >
        {{ p.title.split("：")[0] }}
      </button>
    </div>

    <section v-for="p in byPhase" :key="p.phase" class="blueprint__phase" :aria-labelledby="`phase-${p.phase}`">
      <h2 :id="`phase-${p.phase}`" class="blueprint__phase-title">{{ p.title }}</h2>
      <p class="blueprint__phase-goal">{{ p.goal }}</p>
      <div class="blueprint__grid">
        <HudPanel
          v-for="item in p.items"
          :id="`bp-${item.id}`"
          :key="item.id"
          as="article"
          :title="item.title"
          :code="`P${item.phase}-${item.id.toUpperCase()}`"
          :heading-level="3"
          :tone="focus === item.id ? 'accent' : 'default'"
          tabindex="-1"
          :data-blueprint="item.id"
        >
          <p class="blueprint__purpose">{{ item.purpose }}</p>
          <p class="blueprint__meta"><strong>主要資料：</strong>{{ item.data.join("、") }}</p>
          <p class="blueprint__meta"><strong>操作流程：</strong></p>
          <ol class="blueprint__flow">
            <li v-for="(s, i) in item.flow" :key="s"><span class="num" aria-hidden="true">{{ i + 1 }}</span>{{ s }}</li>
          </ol>
          <p class="blueprint__meta"><strong>先決條件：</strong>{{ dependencyText(item) }}</p>
          <p class="blueprint__meta"><strong>與現有功能：</strong>{{ item.link }}</p>
        </HudPanel>
      </div>
    </section>

    <p class="blueprint__foot">
      想知道目前已經能用什麼？請看<RouterLink to="/capabilities">功能地圖</RouterLink>。
    </p>
  </div>
</template>

<style scoped>
.blueprint {
  display: grid;
  gap: calc(var(--gap) * 1.5);
  max-width: 1280px;
}
.blueprint__head {
  display: grid;
  gap: 6px;
  justify-items: start;
}
.blueprint__eyebrow {
  margin: 0;
  font-size: 0.72rem;
  letter-spacing: 0.24em;
  color: var(--accent);
}
.blueprint__title {
  margin: 0;
  font-size: clamp(1.5rem, 3vw, 2.1rem);
  text-shadow: 0 0 18px var(--glow);
}
.blueprint__lead,
.blueprint__phase-goal {
  margin: 0;
  max-width: 70ch;
  color: var(--ink-dim);
}
.blueprint__phases {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.blueprint__phases [aria-pressed="true"] {
  border-color: var(--accent);
  color: var(--accent);
}
.blueprint__phase {
  display: grid;
  gap: 8px;
}
.blueprint__phase-title {
  margin: 0;
  font-size: 1.15rem;
}
.blueprint__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: var(--gap);
}
.blueprint__purpose {
  margin: 0 0 8px;
}
.blueprint__meta {
  margin: 8px 0 0;
  font-size: 0.85rem;
  color: var(--ink-dim);
}
.blueprint__flow {
  list-style: none;
  margin: 6px 0 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  font-size: 0.85rem;
}
.blueprint__flow li {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 8px;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
}
.blueprint__flow .num {
  color: var(--accent);
  font-size: 0.75rem;
}
.blueprint__foot {
  margin: 0;
  color: var(--ink-dim);
}
.blueprint__foot a {
  color: var(--accent);
}
@media (max-width: 420px) {
  .blueprint__grid {
    grid-template-columns: 1fr;
  }
}
</style>
