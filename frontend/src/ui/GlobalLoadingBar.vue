<script setup lang="ts">
import { computed } from "vue";
import { inflight } from "../api/client";

const loading = computed(() => inflight.value > 0);
</script>

<template>
  <div v-if="loading" class="gload" role="progressbar" aria-label="讀取中" data-testid="global-loading">
    <span class="gload__beam" />
  </div>
</template>

<style scoped>
.gload {
  position: fixed;
  inset: 0 0 auto 0;
  height: 3px;
  z-index: 100;
  overflow: hidden;
  background: color-mix(in srgb, var(--accent) 15%, transparent);
}
.gload__beam {
  position: absolute;
  inset: 0 auto 0 0;
  width: 35%;
  background: linear-gradient(90deg, transparent, var(--accent), var(--accent-2), transparent);
  box-shadow: 0 0 12px var(--accent);
  animation: gload-run 1.1s cubic-bezier(0.4, 0, 0.2, 1) infinite;
}
@keyframes gload-run {
  from {
    transform: translateX(-100%);
  }
  to {
    transform: translateX(300%);
  }
}
@media (prefers-reduced-motion: reduce) {
  .gload__beam {
    animation: none;
    width: 100%;
    opacity: 0.8;
  }
}
</style>
