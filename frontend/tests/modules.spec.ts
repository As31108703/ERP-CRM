import { describe, expect, it } from "vitest";
import { buildConfigError, changeModules, launchKitUrl, validateCompany } from "../src/lib/modules";

describe("changeModules", () => {
  it("enabling sales adds inventory and wallets", () => {
    const { modules, notice } = changeModules(["crm"], "sales", true);
    expect([...modules].sort()).toEqual(["crm", "inventory", "sales", "wallets"]);
    expect(notice).toBe("一併啟用：商品庫存、測試幣流水。");
  });

  it("disabling wallets removes sales, services, manufacturing", () => {
    const all = ["inventory", "sales", "wallets", "services", "crm", "projects", "manufacturing", "administration"];
    const { modules, notice } = changeModules(all, "wallets", false);
    expect(modules).toEqual(["inventory", "crm", "projects", "administration"]);
    expect(notice).toBe("一併關閉：模擬訂單、報價與服務、BOM 與製造。");
  });

  it("no notice when nothing else changes, and order follows the module registry", () => {
    expect(changeModules(["projects"], "crm", true)).toEqual({ modules: ["crm", "projects"], notice: null });
    expect(changeModules(["crm", "projects"], "projects", false)).toEqual({ modules: ["crm"], notice: null });
  });

  it("uses dependencies supplied by the template catalog when given", () => {
    const { modules } = changeModules([], "projects", true, { projects: ["crm"] });
    expect(modules).toEqual(["crm", "projects"]);
  });
});

describe("build config validation", () => {
  it("company name: required, ≤100, no control characters", () => {
    expect(validateCompany("  ")).toBe("請輸入店名或公司名稱。");
    expect(validateCompany("a".repeat(101))).toBe("名稱最多 100 個字。");
    expect(validateCompany("甲\u0007乙")).toBe("名稱不可包含控制字元。");
    expect(validateCompany(" 星軌示範商店 ")).toBeNull();
  });

  it("rejects unknown industry, empty and inconsistent module sets", () => {
    const ids = ["retail", "general"];
    expect(buildConfigError({ industry: "x", company: "甲", modules: ["crm"] }, ids)).toBe("請選擇產業範本。");
    expect(buildConfigError({ industry: "retail", company: "甲", modules: [] }, ids)).toBe("請至少啟用一個功能模組。");
    expect(buildConfigError({ industry: "retail", company: "甲", modules: ["sales"] }, ids)).toBe(
      "模擬訂單需要先啟用：商品庫存、測試幣流水。",
    );
    expect(buildConfigError({ industry: "retail", company: "甲", modules: ["crm", "bank"] }, ids)).toBe("包含未知的功能模組。");
    expect(buildConfigError({ industry: "retail", company: "甲", modules: ["crm"] }, ids)).toBeNull();
  });

  it("launch kit url follows the backup contract", () => {
    expect(launchKitUrl({ industry: "retail", company: " 甲 & 乙 ", modules: ["inventory", "sales"] })).toBe(
      "/api/v1/backup/launch-kit?industry=retail&company_name=%E7%94%B2%20%26%20%E4%B9%99&modules=inventory,sales",
    );
  });
});
