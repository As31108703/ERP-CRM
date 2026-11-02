<script setup lang="ts">
import { computed, defineAsyncComponent, type Component } from "vue";
import { useRoute } from "vue-router";
import PlaceholderView from "./PlaceholderView.vue";

/** `/m/:module` 依模組載入對應頁面；未知模組顯示建置中。 */
const PAGES: Record<string, Component> = {
  crm: defineAsyncComponent(() => import("../modules/crm/CrmPage.vue")),
  inventory: defineAsyncComponent(() => import("../modules/inventory/InventoryPage.vue")),
  sales: defineAsyncComponent(() => import("../modules/sales/SalesPage.vue")),
  wallets: defineAsyncComponent(() => import("../modules/wallets/WalletsPage.vue")),
  services: defineAsyncComponent(() => import("../modules/services/ServicesPage.vue")),
  manufacturing: defineAsyncComponent(() => import("../modules/manufacturing/ManufacturingPage.vue")),
  projects: defineAsyncComponent(() => import("../modules/projects/ProjectsPage.vue")),
};

const route = useRoute();
const module = computed(() => (typeof route.params.module === "string" ? route.params.module : ""));
const page = computed(() => PAGES[module.value] ?? PlaceholderView);
</script>

<template>
  <component :is="page" :key="module" />
</template>
