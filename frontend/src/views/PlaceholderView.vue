<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";

const route = useRoute();
const title = computed(() => {
  const module = route.params.module;
  return typeof module === "string" ? `模組：${module}` : String(route.meta.title ?? "");
});
</script>

<template>
  <section class="placeholder" :data-testid="`page-${String(route.name)}`">
    <h1>{{ title }}</h1>
    <p>此頁面建置中。</p>
  </section>
</template>
