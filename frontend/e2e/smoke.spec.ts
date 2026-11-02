import { readFile } from "node:fs/promises";
import { expect, test, type Page } from "@playwright/test";

/**
 * 煙霧測試：每個測試都是全新的瀏覽器 context（新 session、新工作區），
 * 從建置精靈開始，走過一條真實的前端 → API → 資料庫路徑。
 */

async function buildWorkspace(page: Page, company: string, industry = "general"): Promise<void> {
  await page.goto("/#/build");
  await expect(page.getByTestId("page-build")).toBeVisible();
  await page.getByTestId("company-input").fill(company);
  await page.locator(`[data-industry="${industry}"]`).click();
  await page.getByTestId("build-next").click();
  await expect(page.getByTestId("step-heading")).toHaveText("確認推薦功能");
  await page.getByTestId("build-next").click();
  await expect(page.getByTestId("step-heading")).toHaveText("建立我的系統");
  await expect(page.getByTestId("build-summary")).toContainText(company);
  await page.getByTestId("build-create").click();
  await expect(page).toHaveURL(/#\/overview$/);
  await expect(page.getByTestId("page-overview")).toBeVisible();
}

/** 表單對話框的送出鈕（FormDialog 的 type=submit 按鈕）。 */
function submitButton(page: Page, label: string) {
  return page.getByRole("dialog").getByRole("button", { name: label, exact: true });
}

async function createProduct(page: Page, name: string, sku: string): Promise<void> {
  await page.getByRole("button", { name: "快速新增" }).click();
  await page.getByTestId("quick-create-product").click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("商品名稱").fill(name);
  await dialog.getByLabel("SKU").fill(sku);
  await submitButton(page, "確認模擬操作").click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
}

async function inventoryText(page: Page): Promise<string> {
  await page.goto("/#/m/inventory");
  const inventory = page.getByTestId("page-inventory");
  await expect(inventory).toBeVisible();
  return inventory.innerText();
}

test("build wizard creates workspace and lands on overview", async ({ page }) => {
  await buildWorkspace(page, "星軌煙霧測試商店", "retail");
  await expect(page.getByTestId("first-run-guide")).toBeVisible();
  // 頁首顯示新工作區名稱，且沒有工作區時才能進入的建置頁改為顯示「保留現有工作區」
  await expect(page.locator("body")).toContainText("星軌煙霧測試商店");
  await page.goto("/#/build");
  await expect(page.getByTestId("build-existing")).toBeVisible();
});

test("sales learning path completes 8 steps", async ({ page }) => {
  await buildWorkspace(page, "教學路線測試");
  await page.goto("/#/learning");
  await expect(page.getByTestId("learning-studio")).toBeVisible();
  await page.getByTestId("learning-route-sales").click();
  const progress = page.getByTestId("learning-progress");
  await expect(progress).toContainText("0／8 步驟已確認");

  for (let done = 1; done <= 8; done++) {
    // 執行後畫面停在剛完成的步驟顯示前後讀值，再由使用者前往下一個實作步驟
    if (done > 1) await page.getByTestId("learning-next").click();
    await expect(page.getByTestId("learning-scene-state")).toHaveText("準備實作");
    const execute = page.getByTestId("learning-execute");
    await expect(execute).toBeEnabled();
    await execute.click();
    await expect(progress).toContainText(`${done}／8 步驟已確認`);
    await expect(page.getByTestId("learning-snapshot")).toBeVisible();
  }
  await expect(page.getByTestId("learning-complete")).toBeVisible();
  await expect(page.getByTestId("learning-execute")).toBeDisabled();
});

test("administration demo then CSV download", async ({ page }) => {
  await buildWorkspace(page, "行政示範測試");
  await page.goto("/#/administration");
  await expect(page.getByTestId("page-administration")).toBeVisible();

  const enable = page.getByTestId("admin-enable");
  if (await enable.isVisible()) {
    await enable.click();
    await submitButton(page, "啟用行政模擬").click();
    await expect(page.getByTestId("admin-enable-panel")).toHaveCount(0);
  }

  await page.getByTestId("admin-demo").click();
  await submitButton(page, "建立合成示範").click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByTestId("admin-demo")).toBeDisabled();

  const exportButton = page.getByTestId("admin-export");
  await expect(exportButton).toBeEnabled();
  const [download] = await Promise.all([page.waitForEvent("download"), exportButton.click()]);
  expect(download.suggestedFilename()).toMatch(/^erpcrm-admin-[a-z]+-\d{4}-\d{2}-\d{2}\.csv$/);
  const csv = await readFile((await download.path())!, "utf-8");
  const lines = csv.split(/\r?\n/).filter((l) => l.trim() !== "");
  expect(lines.length).toBeGreaterThan(1);
});

test("export then import restores data", async ({ page }) => {
  await buildWorkspace(page, "備份還原測試");
  await createProduct(page, "備份前商品", "E2E-KEEP");

  await page.goto("/#/settings");
  const [download] = await Promise.all([page.waitForEvent("download"), page.getByTestId("export-backup").click()]);
  expect(download.suggestedFilename()).toBe("erpcrm-sim-backup.json");
  const backupPath = (await download.path())!;
  const backup = JSON.parse(await readFile(backupPath, "utf-8"));
  expect(backup.format).toBe("erpcrm-sim-backup");

  await createProduct(page, "備份後商品", "E2E-DROP");
  expect(await inventoryText(page)).toContain("備份後商品");

  await page.goto("/#/settings");
  await page.getByTestId("import-file").setInputFiles(backupPath);
  const dialog = page.getByRole("dialog", { name: "還原 SIM 備份" });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "確認還原模擬資料" }).click();
  await expect(dialog.locator("[data-backup-phase]")).toHaveAttribute("data-backup-phase", "done");
  await dialog.getByText("關閉", { exact: true }).click();

  const text = await inventoryText(page);
  expect(text).toContain("備份前商品");
  expect(text).not.toContain("備份後商品");
});

test("theme preview blocks quick create", async ({ page }) => {
  await buildWorkspace(page, "主題試看測試");
  const quick = page.getByRole("button", { name: "快速新增" });
  await expect(quick).toBeEnabled();

  await page.goto("/#/design");
  await expect(page.getByTestId("page-design")).toBeVisible();
  await page.locator("[data-theme-card] [data-action=preview]:not([disabled])").first().click();
  await expect(page.getByTestId("design-preview-bar")).toBeVisible();
  await expect(quick).toBeDisabled();
  await expect(page.getByTestId("quick-create-dialog")).toHaveCount(0);

  // 取消試看後恢復資料操作
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("design-preview-bar")).toHaveCount(0);
  await expect(quick).toBeEnabled();
  await quick.click();
  await expect(page.getByTestId("quick-create-dialog")).toBeVisible();
});

test("learning action dock sticks to the viewport bottom on phones", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await buildWorkspace(page, "手機操作列測試");
  await page.goto("/#/learning");
  const dock = page.getByTestId("learning-action-dock");
  await expect(dock).toBeVisible();
  // 760px 以下操作列以 Teleport 掛到 body，固定貼齊視窗底部
  await expect(page.locator("body > [data-testid=learning-action-dock]")).toHaveCount(1);
  const gap = await dock.evaluate((el) => window.innerHeight - el.getBoundingClientRect().bottom);
  expect(Math.abs(gap)).toBeLessThanOrEqual(1);
});
