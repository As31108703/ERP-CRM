import { describe, expect, it } from "vitest";
import {
  formatDateTime,
  formatSim,
  localInputToIso,
  parseSim,
  simInput,
  SIM_MAX_MINOR,
  toLocalInput,
} from "../src/lib/format";

describe("formatSim", () => {
  it('formatSim(123456) === "1,234.56 SIM"', () => {
    expect(formatSim(123456)).toBe("1,234.56 SIM");
  });

  it("keeps two decimals, groups thousands and handles negatives", () => {
    expect(formatSim(0)).toBe("0.00 SIM");
    expect(formatSim(5)).toBe("0.05 SIM");
    expect(formatSim(10000)).toBe("100.00 SIM");
    expect(formatSim(100_000_000_000)).toBe("1,000,000,000.00 SIM");
    expect(formatSim(-123456)).toBe("-1,234.56 SIM");
  });

  it("treats missing or non-integer input as zero", () => {
    expect(formatSim(undefined)).toBe("0.00 SIM");
    expect(formatSim(Number.NaN)).toBe("0.00 SIM");
  });
});

describe("parseSim", () => {
  it("parseSim rejects 3 decimals", () => {
    expect(parseSim("1.234")).toBeNull();
    expect(parseSim("0.001")).toBeNull();
  });

  it("converts SIM text to minor units without floating error", () => {
    expect(parseSim("1234.56")).toBe(123456);
    expect(parseSim("1,234.5")).toBe(123450);
    expect(parseSim("100")).toBe(10000);
    expect(parseSim(" 0.29 ")).toBe(29);
    expect(parseSim("19.99 SIM")).toBe(1999);
    expect(parseSim("０．５")).toBe(50);
  });

  it("rejects empty, negative, exponent and over-limit input", () => {
    for (const bad of ["", " ", "-1", "1e3", "abc", "1.", ".5", "1..2", "Infinity"]) {
      expect(parseSim(bad), bad).toBeNull();
    }
    expect(parseSim("10000000")).toBe(SIM_MAX_MINOR);
    expect(parseSim("10000000.01")).toBeNull();
  });

  it("simInput round-trips through parseSim", () => {
    for (const minor of [0, 1, 50, 10000, 123456]) {
      expect(parseSim(simInput(minor))).toBe(minor);
    }
    expect(simInput(10000)).toBe("100");
    expect(simInput(123450)).toBe("1234.50");
  });
});

describe("datetime helpers", () => {
  it("local datetime input converts to ISO and back", () => {
    const ms = Date.UTC(2026, 10, 2, 4, 30);
    const local = toLocalInput(ms);
    expect(local).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/);
    expect(localInputToIso(local)).toBe(new Date(ms).toISOString());
    expect(localInputToIso("not a date")).toBeNull();
  });

  it("formats in Asia/Taipei", () => {
    expect(formatDateTime("2026-11-01T16:30:00Z")).toContain("2026/11/02");
    expect(formatDateTime("2026-11-01T16:30:00Z")).toContain("00:30");
    expect(formatDateTime("garbage")).toBe("—");
  });
});
