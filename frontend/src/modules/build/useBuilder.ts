import { computed, ref, type Ref } from "vue";
import { useRouter } from "vue-router";
import type { Template } from "../../api/types";
import { buildConfigError, changeModules, MODULE_DEPENDENCIES, type BuildConfig } from "../../lib/modules";
import { useWorkspaceStore } from "../../stores/workspace";

export const SETUP_PATH = "/api/v1/workspace/setup";

/** 範本卡片的示範行業與圖示（只用於顯示）。 */
export const INDUSTRY_HINTS: Record<string, { examples: string; glyph: string }> = {
  retail: { examples: "選物店、文具店、生活雜貨", glyph: "◇" },
  wholesale: { examples: "食材批發、零件經銷、通路供貨", glyph: "▣" },
  service: { examples: "設計工作室、顧問、維修服務", glyph: "✦" },
  restaurant: { examples: "咖啡館、便當店、烘焙坊", glyph: "◎" },
  manufacturing: { examples: "小型加工廠、組裝線、手作品牌", glyph: "⚙" },
  ecommerce: { examples: "網路商店、團購、訂閱盒", glyph: "⬡" },
  projects: { examples: "系統整合、活動策劃、工程專案", glyph: "◈" },
  general: { examples: "想看全部模組的企業", glyph: "✧" },
};

/** 保留期限說明：公開試用顯示清除時間或時數，自架模式提醒定期匯出備份（建置頁與設定頁共用）。 */
export function retentionSummary(store: ReturnType<typeof useWorkspaceStore>): string {
  const expires = store.view?.expires_at;
  if (expires) {
    const at = new Date(expires).toLocaleString("zh-TW", { timeZone: "Asia/Taipei", hour12: false });
    return `公開試用資料預計於 ${at} 清除；持續使用會自動延後。`;
  }
  const hours = store.templates?.defaults.retention_hours;
  if (hours) return `公開試用模式：工作區 ${hours} 小時沒有存取就會整筆清除。`;
  return "自架模式：資料永久保留在這台伺服器上，請定期匯出備份。";
}

/**
 * 建置精靈與自訂建置共用：範本、模組勾選（自動補相依／連帶關閉）、檢查與建立工作區。
 * `config` 由呼叫端提供，精靈會把它同步到 sessionStorage 草稿。
 */
export function useBuilder(config: Ref<BuildConfig>) {
  const store = useWorkspaceStore();
  const router = useRouter();
  const notice = ref("");
  const localError = ref("");
  const creating = ref(false);

  const templates = computed<Template[]>(() => store.templates?.items ?? []);
  const industryIds = computed(() => templates.value.map((t) => t.id));
  const template = computed(() => templates.value.find((t) => t.id === config.value.industry) ?? null);
  const dependencies = computed<Readonly<Record<string, readonly string[]>>>(
    () => templates.value[0]?.module_dependencies ?? MODULE_DEPENDENCIES,
  );
  const configError = computed(() => buildConfigError(config.value, industryIds.value, dependencies.value));
  const recommended = computed(() => {
    const t = template.value;
    if (!t) return false;
    const a = [...t.modules].sort().join(",");
    return a === [...config.value.modules].sort().join(",");
  });

  const locked = computed(() => store.busy || store.pending !== null || store.designPreview || creating.value);
  const lockReason = computed(() => {
    if (store.designPreview) return "外觀試看中，請先套用或取消試看。";
    if (store.pending) return "上次操作尚未確認，請先按「確認原操作結果」。";
    if (store.busy || creating.value) return "正在處理中，請稍候。";
    return "";
  });

  function chooseIndustry(id: string): void {
    const t = templates.value.find((x) => x.id === id);
    if (!t || locked.value) return;
    config.value = { ...config.value, industry: id, modules: [...t.modules] };
    notice.value = "";
  }

  function toggleModule(id: string, on: boolean): void {
    if (locked.value) return;
    const result = changeModules(config.value.modules, id, on, dependencies.value);
    config.value = { ...config.value, modules: result.modules };
    notice.value = result.notice ?? "";
  }

  function restoreRecommended(): void {
    if (template.value && !locked.value) {
      config.value = { ...config.value, modules: [...template.value.modules] };
      notice.value = "已恢復範本推薦的功能。";
    }
  }

  const retentionText = computed(() => retentionSummary(store));

  /** 送出 setup；成功後前往工作總覽。重複點擊、鎖定或已有工作區時不送出。 */
  async function create(): Promise<boolean> {
    if (creating.value || locked.value || store.hasWorkspace) return false;
    localError.value = configError.value ?? "";
    if (configError.value) return false;
    creating.value = true;
    notice.value = "";
    try {
      const { industry, company, modules } = config.value;
      const result = await store.run("POST", SETUP_PATH, { industry, company_name: company.trim(), modules });
      if (!result) {
        localError.value = store.error || "尚未完成建立，請查看上方訊息後再試。";
        return false;
      }
      await router.push("/overview");
      return true;
    } finally {
      creating.value = false;
    }
  }

  return {
    store,
    templates,
    template,
    dependencies,
    configError,
    recommended,
    locked,
    lockReason,
    notice,
    localError,
    creating,
    retentionText,
    chooseIndustry,
    toggleModule,
    restoreRecommended,
    create,
  };
}
