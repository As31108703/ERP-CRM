<script setup lang="ts">
import { computed } from "vue";
import { RouterLink, useRoute } from "vue-router";
import { useWorkspaceStore } from "../stores/workspace";
import { ICONS, MODULE_LABELS } from "./icons";

/** 艦橋導覽軌：桌面為左側軌道（分組），760px 以下收成底部列。 */

interface NavItem {
  key: string;
  label: string;
  to: string;
  icon: string;
  testid?: string;
}

const store = useWorkspaceStore();
const route = useRoute();

const groups = computed<{ title: string; code: string; items: NavItem[] }[]>(() => {
  const ws = store.view?.workspace;
  if (!ws) {
    return [
      {
        title: "啟航",
        code: "SYS",
        items: [
          { key: "build", label: "快速上手", to: "/build", icon: "build" },
          { key: "design", label: "主題圖庫", to: "/design", icon: "design" },
          { key: "capabilities", label: "功能地圖", to: "/capabilities", icon: "capabilities" },
          { key: "blueprint", label: "系統藍圖", to: "/blueprint", icon: "blueprint" },
        ],
      },
    ];
  }
  const modules = ws.modules.filter((m) => m in MODULE_LABELS);
  return [
    {
      title: "艦橋",
      code: "BRG",
      items: [
        { key: "overview", label: "工作總覽", to: "/overview", icon: "overview" },
        { key: "learning", label: "沉浸教學", to: "/learning", icon: "learning" },
        { key: "build", label: "快速上手", to: "/build", icon: "build" },
        { key: "capabilities", label: "功能地圖", to: "/capabilities", icon: "capabilities" },
        { key: "design", label: "主題圖庫", to: "/design", icon: "design" },
      ],
    },
    {
      title: "營運模組",
      code: "OPS",
      items: modules.map((m) => ({ key: `m-${m}`, label: MODULE_LABELS[m], to: `/m/${m}`, icon: m })),
    },
    {
      title: "後勤",
      code: "LOG",
      items: [
        { key: "administration", label: "行政工作台", to: "/administration", icon: "administration", testid: "office-nav" },
        { key: "reports", label: "模擬報表", to: "/reports", icon: "reports" },
        { key: "settings", label: "設定與資料", to: "/settings", icon: "settings" },
      ],
    },
  ].filter((g) => g.items.length > 0);
});

function isActive(item: NavItem): boolean {
  return route.path === item.to;
}
</script>

<template>
  <nav class="rail" aria-label="艦橋導覽">
    <div v-for="group in groups" :key="group.code" class="rail__group">
      <p class="rail__group-title">
        <span>{{ group.title }}</span>
        <span class="num rail__group-code" aria-hidden="true">{{ group.code }}</span>
      </p>
      <ul class="rail__list">
        <li v-for="item in group.items" :key="item.key">
          <RouterLink
            :to="item.to"
            class="rail__link"
            :class="{ 'is-active': isActive(item) }"
            :aria-current="isActive(item) ? 'page' : undefined"
            :data-testid="item.testid"
          >
            <svg class="rail__icon" viewBox="0 0 24 24" aria-hidden="true"><path :d="ICONS[item.icon] ?? ICONS.overview" /></svg>
            <span class="rail__label">{{ item.label }}</span>
          </RouterLink>
        </li>
      </ul>
    </div>
    <p class="rail__foot">每位訪客獨立 · 只保存模擬資料</p>
  </nav>
</template>

<style scoped>
.rail {
  display: flex;
  flex-direction: column;
  gap: calc(var(--gap) * 1.4);
  padding: var(--pad) calc(var(--pad) * 0.75);
  height: 100%;
  overflow-y: auto;
  background: linear-gradient(180deg, color-mix(in srgb, var(--surface) 92%, transparent), color-mix(in srgb, var(--bg-deep) 90%, transparent));
  border-right: 1px solid var(--line);
  box-shadow: inset -1px 0 0 color-mix(in srgb, var(--accent) 18%, transparent);
}
.rail__group-title {
  display: flex;
  justify-content: space-between;
  margin: 0 0 6px;
  padding: 0 8px;
  font-size: 0.7rem;
  letter-spacing: 0.2em;
  color: var(--ink-faint);
}
.rail__group-code {
  color: var(--accent);
  opacity: 0.7;
}
.rail__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 2px;
}
.rail__link {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: var(--control-h);
  padding: 0 10px;
  color: var(--ink-dim);
  text-decoration: none;
  font-size: 0.9rem;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  transition:
    color var(--motion-fast),
    background var(--motion-fast);
}
.rail__link:hover {
  color: var(--ink);
  background: color-mix(in srgb, var(--accent) 8%, transparent);
}
.rail__link.is-active {
  color: var(--ink);
  background: linear-gradient(90deg, color-mix(in srgb, var(--accent) 22%, transparent), transparent);
  border-color: color-mix(in srgb, var(--accent) 35%, transparent);
}
.rail__link.is-active::before {
  content: "";
  position: absolute;
  left: -1px;
  top: 6px;
  bottom: 6px;
  width: 3px;
  background: var(--accent);
  box-shadow: 0 0 10px var(--accent);
}
.rail__icon {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.6;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.is-active .rail__icon {
  stroke: var(--accent);
  filter: drop-shadow(0 0 4px var(--glow));
}
.rail__foot {
  margin: auto 0 0;
  padding: 0 8px;
  font-size: 0.7rem;
  color: var(--ink-faint);
}

/* 手機寬度：底部列 */
@media (max-width: 759.98px) {
  .rail {
    flex-direction: row;
    gap: 0;
    padding: 0 4px;
    height: auto;
    overflow-x: auto;
    overflow-y: hidden;
    border-right: 0;
    border-top: 1px solid var(--line);
    box-shadow: 0 -8px 24px color-mix(in srgb, var(--bg-deep) 70%, transparent);
    background: color-mix(in srgb, var(--surface) 96%, transparent);
    backdrop-filter: blur(6px);
    scrollbar-width: none;
  }
  .rail__group {
    display: contents;
  }
  .rail__group-title,
  .rail__foot {
    display: none;
  }
  .rail__list {
    display: flex;
    gap: 0;
  }
  .rail__link {
    flex-direction: column;
    justify-content: center;
    gap: 2px;
    min-width: 68px;
    min-height: 58px;
    padding: 4px 6px;
    font-size: 0.66rem;
    border: 0;
    border-radius: 0;
  }
  .rail__label {
    white-space: nowrap;
  }
  .rail__link.is-active::before {
    left: 12px;
    right: 12px;
    top: -1px;
    bottom: auto;
    width: auto;
    height: 3px;
  }
  .rail__link.is-active {
    background: linear-gradient(180deg, color-mix(in srgb, var(--accent) 20%, transparent), transparent);
  }
}
</style>
