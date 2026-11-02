import { createApp } from "vue";
import { createPinia } from "pinia";
import App from "./App.vue";
import { createAppRouter } from "./router";
import { usePreferencesStore } from "./stores/preferences";
import "./themes/tokens.css";
import "./themes/base.css";

const app = createApp(App);
const pinia = createPinia();
app.use(pinia);
// 先建立偏好 store，讓 <html data-theme-id/data-theme/data-density> 在第一次繪製前就套好。
usePreferencesStore(pinia);
app.use(createAppRouter());
app.mount("#app");
