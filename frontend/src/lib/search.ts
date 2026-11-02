/** 搜尋正規化：NFKC（全形轉半形）、轉小寫、折疊空白。 */
export function normalizeSearch(text: string): string {
  return text.normalize("NFKC").toLowerCase().replace(/\s+/g, " ").trim();
}

/** 以空白分詞，每個詞都必須是 haystack 的子字串（haystack 需已正規化）。 */
export function matchesQuery(normalizedHaystack: string, query: string): boolean {
  const tokens = normalizeSearch(query).split(" ").filter(Boolean);
  return tokens.every((t) => normalizedHaystack.includes(t));
}

export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
    : false;
}
