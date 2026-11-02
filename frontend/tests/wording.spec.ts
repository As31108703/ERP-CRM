import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? files(path) : [path];
  });
}

// 以跳脫序列寫「台」字形的寫法，避免本檔自己出現要禁止的字形。
const VARIANT_FORM = "\u53f0\u5317";

describe("wording", () => {
  it("UI copy writes 臺北 to match the backend CSV headers", () => {
    const root = join(__dirname, "..", "src");
    const offenders = files(root).filter((f) => readFileSync(f, "utf8").includes(VARIANT_FORM));
    expect(offenders).toEqual([]);
  });
});
