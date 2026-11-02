import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setSession } from "../src/api/client";
import SettingsPage from "../src/modules/settings/SettingsPage.vue";
import { flush, mountPage, workspace } from "./pageHarness";

/** 可由測試逐步驅動的假 XHR：記錄標頭與內容，由測試觸發上傳進度、上傳完成與伺服器回應。 */
class FakeXhr {
  static instances: FakeXhr[] = [];
  static phaseAtOpen: string | null = null;
  method = "";
  url = "";
  headers: Record<string, string> = {};
  body: string | null = null;
  status = 0;
  responseText = "";
  withCredentials = false;
  upload: {
    onprogress: ((e: { lengthComputable: boolean; loaded: number; total: number }) => void) | null;
    onload: (() => void) | null;
  } = { onprogress: null, onload: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  private responseHeaders: Record<string, string> = {};

  constructor() {
    FakeXhr.instances.push(this);
  }
  open(method: string, url: string): void {
    this.method = method;
    this.url = url;
    FakeXhr.phaseAtOpen = document.querySelector("[data-backup-phase]")?.getAttribute("data-backup-phase") ?? null;
  }
  setRequestHeader(name: string, value: string): void {
    this.headers[name] = value;
  }
  getResponseHeader(name: string): string | null {
    return this.responseHeaders[name.toLowerCase()] ?? null;
  }
  send(body: string): void {
    this.body = body;
  }
  respond(status: number, body: unknown, headers: Record<string, string> = {}): void {
    this.status = status;
    this.responseText = JSON.stringify(body);
    this.responseHeaders = Object.fromEntries(Object.entries(headers).map(([k, v]) => [k.toLowerCase(), v]));
    this.onload?.();
  }
}

const BACKUP = {
  format: "erpcrm-sim-backup",
  format_version: 1,
  exported_at: "2026-11-02T00:00:00Z",
  workspace: { company_name: "星軌示範商店", industry: "general", modules: ["inventory", "sales", "wallets"] },
  collections: { products: [] },
};

function fileOf(content: string, name = "erpcrm-sim-backup.json", size?: number): File {
  const file = new File([content], name, { type: "application/json" });
  if (size !== undefined) Object.defineProperty(file, "size", { value: size });
  return file;
}

async function choose(wrapper: Awaited<ReturnType<typeof mountPage>>["wrapper"], file: File): Promise<void> {
  const input = wrapper.get("[data-testid=import-file]");
  Object.defineProperty(input.element, "files", { value: [file], configurable: true });
  await input.trigger("change");
  // 等待瀏覽器讀檔與預檢完成（讀檔為非同步）
  for (let i = 0; i < 50 && wrapper.text().includes("檢查檔案中"); i += 1) await flush();
  await flush();
}

function phase(): string | null {
  return document.querySelector("[data-backup-phase]")?.getAttribute("data-backup-phase") ?? null;
}

const VIEW = { workspace: null, csrf: "c2", version: 1 };

beforeEach(() => {
  FakeXhr.instances = [];
  FakeXhr.phaseAtOpen = null;
  vi.stubGlobal("XMLHttpRequest", FakeXhr);
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(VIEW), { status: 200, headers: { "Content-Type": "application/json" } })),
  );
  window.sessionStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("backup restore", () => {
  it("rejects non-SIM file before upload", async () => {
    const { wrapper } = await mountPage(SettingsPage, workspace(), { module: "settings" });

    await choose(wrapper, fileOf(JSON.stringify({ ...BACKUP, format: "other-backup" })));
    expect(wrapper.get("[data-testid=import-error]").text()).toContain("不是星軌 SIM 備份");
    expect(wrapper.find("[role=dialog]").exists()).toBe(false);

    await choose(wrapper, fileOf("{not json"));
    expect(wrapper.get("[data-testid=import-error]").text()).toContain("無法解析");

    await choose(wrapper, fileOf(JSON.stringify(BACKUP), "big.json", 8 * 1024 * 1024 + 1));
    expect(wrapper.get("[data-testid=import-error]").text()).toContain("8 MiB");

    const padded = JSON.stringify({ ...BACKUP, collections: { blob: "x".repeat(3 * 1024 * 1024) } });
    await choose(wrapper, fileOf(padded));
    expect(wrapper.get("[data-testid=import-error]").text()).toContain("3 MiB");

    expect(FakeXhr.instances).toHaveLength(0);
    expect(wrapper.find("[role=dialog]").exists()).toBe(false);
  });

  it("progress phases advance in order", async () => {
    const { wrapper } = await mountPage(SettingsPage, workspace(), { module: "settings" });
    setSession({ csrf: "c", version: 7 });
    // 前後空白與縮排在預檢時會被精簡掉
    await choose(wrapper, fileOf(JSON.stringify(BACKUP, null, 2)));
    const dialog = wrapper.get("[role=dialog]");
    expect(dialog.text()).toContain("erpcrm-sim-backup.json");
    expect(dialog.text()).toContain("星軌示範商店");
    expect(phase()).toBe("confirm");

    const confirm = dialog.findAll("button").find((b) => b.text() === "確認還原模擬資料");
    await confirm!.trigger("click");
    await flush();

    expect(FakeXhr.phaseAtOpen).toBe("checking");
    const xhr = FakeXhr.instances[0];
    expect(xhr.method).toBe("POST");
    expect(xhr.url).toBe("/api/v1/backup/import");
    expect(xhr.headers["x-csrf-token"]).toBe("c");
    expect(xhr.headers["If-Match-Version"]).toBe("7");
    expect(xhr.headers["Idempotency-Key"]).toMatch(/^[A-Za-z0-9_-]{8,100}$/);
    expect(xhr.body).toBe(JSON.stringify(BACKUP));

    expect(phase()).toBe("uploading");
    xhr.upload.onprogress?.({ lengthComputable: true, loaded: 50, total: 200 });
    await flush();
    expect(phase()).toBe("uploading");
    expect(wrapper.get("[role=progressbar]").attributes("aria-valuenow")).toBe("25");

    xhr.upload.onload?.();
    await flush();
    expect(phase()).toBe("verifying");

    xhr.respond(200, { result: null, version: 1, csrf: "c2" });
    await flush();
    await flush();
    expect(phase()).toBe("done");
    expect(wrapper.text()).toContain("備份已完整檢查並還原");
  });

  it("server rejection keeps data and shows the error", async () => {
    const { wrapper } = await mountPage(SettingsPage, workspace(), { module: "settings" });
    await choose(wrapper, fileOf(JSON.stringify(BACKUP)));
    const confirm = wrapper.get("[role=dialog]").findAll("button").find((b) => b.text() === "確認還原模擬資料");
    await confirm!.trigger("click");
    await flush();
    const xhr = FakeXhr.instances[0];
    xhr.upload.onload?.();
    xhr.respond(422, { error: { code: "backup_invalid", message: "備份內容不一致，未做任何變更。" } });
    await flush();
    await flush();
    expect(phase()).toBe("failed");
    expect(wrapper.get("[role=dialog]").text()).toContain("備份內容不一致");
    // 失敗不保留 pending（4xx 清除）
    expect(window.sessionStorage.getItem("erpcrm.pending.v1")).toBeNull();
  });
});

describe("settings page", () => {
  it("clear asks for confirmation, then posts and goes to build", async () => {
    const { wrapper, run, router } = await mountPage(SettingsPage, workspace(), { module: "settings" });
    await wrapper.get("[data-testid=clear-workspace]").trigger("click");
    expect(run).not.toHaveBeenCalled();
    const ok = wrapper.get("[role=dialog]").findAll("button").find((b) => b.text() === "確認清除");
    await ok!.trigger("click");
    await flush();
    expect(run).toHaveBeenCalledWith("POST", "/api/v1/workspace/clear", {});
    expect(router.currentRoute.value.path).toBe("/build");
  });

  it("lists history newest first, or the empty text", async () => {
    const empty = await mountPage(SettingsPage, workspace(), { module: "settings" });
    expect(empty.wrapper.get("[data-testid=history]").text()).toContain("尚未進行模擬操作。");
    empty.wrapper.unmount();

    const { wrapper } = await mountPage(
      SettingsPage,
      workspace({
        history: [
          { id: "h1", action: "product.create", result: "p1", version: 2, created_at: "2026-11-01T16:30:00Z" },
          { id: "h2", action: "order.pay", result: "o1", version: 3, created_at: "2026-11-01T17:00:00Z" },
        ],
      }),
      { module: "settings" },
    );
    const items = wrapper.get("[data-testid=history]").findAll("li");
    expect(items[0].text()).toContain("order.pay");
    expect(items[0].text()).toContain("2026/11/02 01:00");
    expect(items[1].text()).toContain("product.create");
  });

  it("export links to the backup endpoint with the backup file name", async () => {
    const { wrapper } = await mountPage(SettingsPage, workspace(), { module: "settings" });
    const link = wrapper.get("[data-testid=export-backup]");
    expect(link.attributes("href")).toBe("/api/v1/backup/export");
    expect(link.attributes("download")).toBe("erpcrm-sim-backup.json");
  });
});
