import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

describe("storage", () => {
  beforeEach(() => {
    vi.resetModules();
    window.localStorage.clear();
    window.sessionStorage.clear();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("uses the real storage when it works", async () => {
    const { safeLocal } = await import("../src/lib/storage");
    expect(safeLocal.set("erpcrm.test", "1")).toBe(true);
    expect(window.localStorage.getItem("erpcrm.test")).toBe("1");
    expect(safeLocal.get("erpcrm.test")).toBe("1");
    safeLocal.remove("erpcrm.test");
    expect(safeLocal.get("erpcrm.test")).toBeNull();
    expect(safeLocal.volatile).toBe(false);
  });

  it("falls back to memory when storage throws", async () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    const { safeLocal } = await import("../src/lib/storage");
    expect(safeLocal.set("erpcrm.theme.v1", "bridge")).toBe(true);
    expect(safeLocal.get("erpcrm.theme.v1")).toBe("bridge");
    expect(safeLocal.volatile).toBe(true);
    safeLocal.remove("erpcrm.theme.v1");
    expect(safeLocal.get("erpcrm.theme.v1")).toBeNull();
  });

  it("falls back to memory when the storage accessor itself throws", async () => {
    const { createSafeStorage } = await import("../src/lib/storage");
    const store = createSafeStorage(() => {
      throw new DOMException("denied", "SecurityError");
    });
    expect(store.get("erpcrm.x")).toBeNull();
    expect(store.set("erpcrm.x", "v")).toBe(true);
    expect(store.get("erpcrm.x")).toBe("v");
    expect(store.volatile).toBe(true);
  });

  it("keeps local and session storage independent", async () => {
    const { safeLocal, safeSession } = await import("../src/lib/storage");
    safeSession.set("erpcrm.pending.v1", "p");
    expect(window.sessionStorage.getItem("erpcrm.pending.v1")).toBe("p");
    expect(safeLocal.get("erpcrm.pending.v1")).toBeNull();
  });
});
