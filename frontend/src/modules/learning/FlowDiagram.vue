<script setup lang="ts">
import { computed } from "vue";
import type { LearningFact } from "../../api/types";
import { nodeFact, nodeGlyph, nodeLabel } from "./learning";

/**
 * 流程示意圖：節點以光束串接，目前章節的節點發光脈衝。
 * `still` 為真（暫停或系統要求減少動態）時完全靜止。
 */
const props = defineProps<{
  title: string;
  nodes: string[];
  facts: LearningFact[];
  current: number;
  still: boolean;
}>();

const items = computed(() =>
  props.nodes.map((node, i) => ({
    key: `${node}-${i}`,
    glyph: nodeGlyph(node),
    label: nodeLabel(node),
    fact: nodeFact(node, props.facts),
    current: i === props.current,
  })),
);
</script>

<template>
  <div class="flow" :class="{ 'is-still': still }" data-testid="learning-diagram" role="group" :aria-label="`${title}流程示意`">
    <div class="flow__beam" aria-hidden="true"><span /></div>
    <ol class="flow__nodes" :style="{ '--n': items.length }">
      <li v-for="(n, i) in items" :key="n.key" class="flow__node" :data-node="nodes[i]" :class="{ 'is-current': n.current }" :style="{ '--i': i }">
        <span class="flow__glyph" aria-hidden="true">{{ n.glyph }}</span>
        <strong class="flow__label">{{ n.label }}</strong>
        <span class="flow__fact">{{ n.fact }}</span>
        <small v-if="n.current" class="flow__here">目前章節</small>
      </li>
    </ol>
  </div>
</template>

<style scoped>
.flow {
  position: relative;
  padding: 8px 0 4px;
}
.flow__beam {
  position: absolute;
  top: 30px;
  left: 8%;
  right: 8%;
  height: 2px;
  background: linear-gradient(90deg, var(--accent), var(--line-strong) 50%, var(--accent-2));
  overflow: hidden;
}
.flow__beam span {
  position: absolute;
  top: -1px;
  left: -20%;
  width: 20%;
  height: 4px;
  background: linear-gradient(90deg, transparent, var(--accent), transparent);
  animation: flow-travel 3.6s linear infinite;
}
.flow__nodes {
  position: relative;
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(var(--n), minmax(0, 1fr));
  gap: 8px;
}
.flow__node {
  display: grid;
  justify-items: center;
  text-align: center;
  gap: 4px;
  min-width: 0;
}
.flow__glyph {
  width: 44px;
  height: 44px;
  display: grid;
  place-items: center;
  font-family: var(--font-mono);
  font-size: 1.1rem;
  color: var(--accent);
  background: var(--bg-deep);
  border: 1px solid var(--line-strong);
  clip-path: polygon(25% 0, 75% 0, 100% 50%, 75% 100%, 25% 100%, 0 50%);
}
.flow__node.is-current .flow__glyph {
  color: var(--accent-ink);
  background: var(--accent);
  animation: flow-pulse 1.8s ease-in-out infinite;
  animation-delay: calc(var(--i) * 0.12s);
}
.flow__label {
  font-size: 0.86rem;
}
.flow__fact {
  font-size: 0.74rem;
  color: var(--ink-dim);
  overflow-wrap: anywhere;
}
.flow__here {
  font-size: 0.7rem;
  color: var(--accent-2);
  letter-spacing: 0.08em;
}
@keyframes flow-pulse {
  0%,
  100% {
    filter: drop-shadow(0 0 2px var(--glow));
  }
  50% {
    filter: drop-shadow(0 0 12px var(--accent));
  }
}
@keyframes flow-travel {
  to {
    left: 100%;
  }
}
.flow.is-still .flow__beam span,
.flow.is-still .flow__node.is-current .flow__glyph {
  animation: none;
}
.flow.is-still .flow__beam span {
  display: none;
}
@media (prefers-reduced-motion: reduce) {
  .flow__beam span,
  .flow__node.is-current .flow__glyph {
    animation: none;
  }
  .flow__beam span {
    display: none;
  }
}
@media (max-width: 760px) {
  .flow__nodes {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .flow__beam {
    display: none;
  }
}
</style>
