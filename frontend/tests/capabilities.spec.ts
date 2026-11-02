import { describe, expect, it } from "vitest";
import {
  CAPABILITIES,
  CAPABILITY_GROUPS,
  capabilityDestination,
  destinationPath,
  filterCapabilities,
} from "../src/modules/capabilities/capabilities";
import { MODULE_ORDER } from "../src/lib/modules";
import { routes } from "../src/router";
import { BLUEPRINT } from "../src/modules/blueprint/blueprint";

const PAGE_NAMES = routes.map((r) => r.name).filter((n): n is string => typeof n === "string");

describe("capabilities", () => {
  it("34 items, every module reference is a real module", () => {
    expect(CAPABILITIES).toHaveLength(34);
    expect(CAPABILITIES.map((c) => c.id)).toEqual(Array.from({ length: 34 }, (_, i) => `CAP${String(i + 1).padStart(2, "0")}`));
    for (const c of CAPABILITIES) {
      expect(CAPABILITY_GROUPS).toContain(c.group);
      for (const m of c.requires ?? []) expect(MODULE_ORDER).toContain(m);
      for (const r of c.routes ?? []) {
        expect(MODULE_ORDER).toContain(r.module);
        for (const m of r.requires) expect(MODULE_ORDER).toContain(m);
      }
      if (c.module) {
        expect([...MODULE_ORDER, ...PAGE_NAMES]).toContain(c.module);
        expect(c.status).not.toBe("planned");
      } else {
        expect(c.status).toBe("planned");
      }
      if (c.blueprint) expect(BLUEPRINT.map((b) => b.id)).toContain(c.blueprint);
    }
  });

  it("every destination resolves to a real route", async () => {
    const { createAppRouter } = await import("../src/router");
    const { createMemoryHistory } = await import("vue-router");
    const router = createAppRouter(createMemoryHistory());
    for (const c of CAPABILITIES) {
      if (!c.module) continue;
      const resolved = router.resolve(destinationPath(c.module));
      expect(resolved.matched[0]?.path).not.toBe("/:rest(.*)*");
    }
  });

  it("destination: planned null, no workspace build, routes pick the first satisfied", () => {
    const planned = CAPABILITIES.find((c) => c.status === "planned")!;
    expect(capabilityDestination(planned, ["crm"])).toBeNull();
    const ar = CAPABILITIES.find((c) => c.id === "CAP06")!;
    expect(capabilityDestination(ar, null)).toBe("build");
    expect(capabilityDestination(ar, ["services", "crm", "wallets"])).toBe("services");
    expect(capabilityDestination(ar, ["crm"])).toBe("build");
    const crm = CAPABILITIES.find((c) => c.id === "CAP11")!;
    expect(capabilityDestination(crm, ["crm"])).toBe("crm");
    expect(capabilityDestination(crm, ["projects"])).toBe("build");
  });

  it("filter matches NFKC tokens over id, title, group and texts", () => {
    expect(filterCapabilities("ｃａｐ１１", "", "").map((c) => c.id)).toEqual(["CAP11"]);
    expect(filterCapabilities("", "財務與稅務", "planned").every((c) => c.group === "財務與稅務" && c.status === "planned")).toBe(true);
    expect(filterCapabilities("不存在的關鍵字", "", "")).toEqual([]);
  });

  it("blueprint lists the planned enterprise modules with purpose, flow and phase", () => {
    const titles = BLUEPRINT.map((b) => b.title).join(" ");
    for (const word of ["總帳", "應收", "應付", "資金", "稅務", "固定資產", "人資", "薪資", "預算"]) expect(titles).toContain(word);
    for (const b of BLUEPRINT) {
      expect(b.purpose.length).toBeGreaterThan(0);
      expect(b.flow.length).toBeGreaterThanOrEqual(3);
      expect(b.phase).toBeGreaterThanOrEqual(1);
    }
  });
});
