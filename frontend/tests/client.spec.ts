import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type Call = { url: string; init: RequestInit };

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

function mockFetch(...responses: Array<Response | Error>) {
  const calls: Call[] = [];
  const fn = vi.fn(async (url: string, init: RequestInit) => {
    calls.push({ url, init });
    const next = responses.shift();
    if (!next) throw new Error("unexpected fetch");
    if (next instanceof Error) throw next;
    return next;
  });
  vi.stubGlobal("fetch", fn);
  return calls;
}

type ErrShape = { status: number; code: string; message: string; retryAfterMs: number | null };

async function failure(p: Promise<unknown>): Promise<ErrShape> {
  try {
    await p;
  } catch (e) {
    return e as ErrShape;
  }
  throw new Error("expected rejection");
}

function header(call: Call, name: string): string | null {
  return new Headers(call.init.headers).get(name);
}

async function load() {
  const client = await import("../src/api/client");
  const pending = await import("../src/api/pending");
  client.setSession({ csrf: "csrf-token-1", version: 7 });
  return { client, pending };
}

describe("api client", () => {
  beforeEach(() => {
    vi.resetModules();
    window.sessionStorage.clear();
    window.localStorage.clear();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("sends csrf, idempotency key and version", async () => {
    const { client, pending } = await load();
    const calls = mockFetch(jsonResponse(200, { result: "o1", version: 8 }));
    const res = await client.mutate<{ result: string }>("POST", "/api/v1/sales/orders", { lines: [] });
    expect(res.result).toBe("o1");
    expect(calls).toHaveLength(1);
    const [call] = calls;
    expect(call.url).toBe("/api/v1/sales/orders");
    expect(call.init.method).toBe("POST");
    expect(call.init.credentials).toBe("same-origin");
    expect(header(call, "x-csrf-token")).toBe("csrf-token-1");
    expect(header(call, "If-Match-Version")).toBe("7");
    expect(header(call, "Content-Type")).toBe("application/json");
    expect(header(call, "Idempotency-Key")).toMatch(/^[A-Za-z0-9_-]{8,100}$/);
    expect(call.init.body).toBe(JSON.stringify({ lines: [] }));
    expect(pending.readPending()).toBeNull();
  });

  it("stores the pending operation before sending", async () => {
    const { client, pending } = await load();
    let seen: unknown = undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        seen = pending.readPending();
        return jsonResponse(200, { result: null });
      }),
    );
    await client.mutate("PATCH", "/api/v1/crm/customers/c1", { name: "甲" });
    expect(seen).toMatchObject({
      method: "PATCH",
      path: "/api/v1/crm/customers/c1",
      body: { name: "甲" },
      version: 7,
    });
    expect(window.sessionStorage.getItem("erpcrm.pending.v1")).toBeNull();
  });

  it("keeps pending on 5xx and network error, clears on 422", async () => {
    const { client, pending } = await load();

    mockFetch(jsonResponse(500, { error: { code: "internal_error", message: "伺服器發生錯誤" } }));
    const e500 = await failure(client.mutate("POST", "/api/v1/wallets", { name: "A" }));
    expect(e500).toBeInstanceOf(client.ApiError);
    expect(e500.status).toBe(500);
    expect(e500.code).toBe("internal_error");
    expect(e500.message).toBe("伺服器發生錯誤");
    expect(pending.readPending()).toMatchObject({ path: "/api/v1/wallets" });

    pending.clearPending();
    mockFetch(new TypeError("Failed to fetch"));
    const eNet = await failure(client.mutate("POST", "/api/v1/wallets", { name: "B" }));
    expect(eNet).toBeInstanceOf(client.ApiError);
    expect(eNet.status).toBe(0);
    expect(eNet.code).toBe("network_error");
    expect(pending.readPending()).toMatchObject({ body: { name: "B" } });

    pending.clearPending();
    mockFetch(jsonResponse(422, { error: { code: "name_invalid", message: "名稱不正確" } }));
    const e422 = await failure(client.mutate("POST", "/api/v1/wallets", { name: "" }));
    expect(e422.status).toBe(422);
    expect(e422.code).toBe("name_invalid");
    expect(pending.readPending()).toBeNull();
  });

  it("keeps pending on 429 rate limit but clears on receipt_limit", async () => {
    const { client, pending } = await load();

    mockFetch(
      jsonResponse(
        429,
        { error: { code: "rate_limited", message: "請稍後再試", retry_after_ms: 1500 } },
        { "Retry-After": "2" },
      ),
    );
    const e429 = await failure(client.mutate("POST", "/api/v1/wallets", { name: "A" }));
    expect(e429.status).toBe(429);
    expect(e429.retryAfterMs).toBe(1500);
    expect(pending.readPending()).not.toBeNull();

    pending.clearPending();
    mockFetch(jsonResponse(429, { error: { code: "receipt_limit", message: "收據已滿" } }));
    await client.mutate("POST", "/api/v1/wallets", { name: "A" }).catch(() => undefined);
    expect(pending.readPending()).toBeNull();
  });

  it("retryPending reuses the same key", async () => {
    const { client, pending } = await load();
    const calls = mockFetch(
      jsonResponse(502, { error: { code: "bad_gateway", message: "閘道錯誤" } }),
      jsonResponse(200, { result: "w1", replayed: true }),
    );
    await client.mutate("POST", "/api/v1/wallets", { name: "A" }).catch(() => undefined);
    const stored = pending.readPending();
    expect(stored).not.toBeNull();

    client.setSession({ csrf: "csrf-token-2", version: 9 });
    const res = await client.retryPending<{ result: string }>();
    expect(res?.result).toBe("w1");
    expect(calls).toHaveLength(2);
    const [first, second] = calls;
    expect(header(second, "Idempotency-Key")).toBe(header(first, "Idempotency-Key"));
    expect(header(second, "Idempotency-Key")).toBe(stored!.key);
    // 重送時沿用原本的版本號與內容，csrf 則用目前的
    expect(header(second, "If-Match-Version")).toBe("7");
    expect(second.init.body).toBe(first.init.body);
    expect(second.init.method).toBe("POST");
    expect(second.url).toBe("/api/v1/wallets");
    expect(header(second, "x-csrf-token")).toBe("csrf-token-2");
    expect(pending.readPending()).toBeNull();
  });

  it("retryPending returns null when nothing is pending", async () => {
    const { client } = await load();
    const calls = mockFetch();
    expect(await client.retryPending()).toBeNull();
    expect(calls).toHaveLength(0);
  });

  it("discards malformed pending entries", async () => {
    const { pending } = await load();
    window.sessionStorage.setItem("erpcrm.pending.v1", "{not json");
    expect(pending.readPending()).toBeNull();
    window.sessionStorage.setItem(
      "erpcrm.pending.v1",
      JSON.stringify({ key: "bad key!", method: "POST", path: "/api/v1/x", body: {}, version: 1 }),
    );
    expect(pending.readPending()).toBeNull();
    window.sessionStorage.setItem(
      "erpcrm.pending.v1",
      JSON.stringify({ key: "abcdefgh12", method: "DELETE", path: "/api/v1/x", body: {}, version: 1 }),
    );
    expect(pending.readPending()).toBeNull();
    window.sessionStorage.setItem(
      "erpcrm.pending.v1",
      JSON.stringify({ key: "abcdefgh12", method: "POST", path: "https://evil.example/api", body: {}, version: 1 }),
    );
    expect(pending.readPending()).toBeNull();
  });

  it("tracks in-flight requests for the loading bar", async () => {
    const { client } = await load();
    let resolve!: (r: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise<Response>((r) => (resolve = r))),
    );
    const p = client.get("/api/v1/workspace/view");
    expect(client.inflight.value).toBe(1);
    resolve(jsonResponse(200, { ok: true }));
    await p;
    expect(client.inflight.value).toBe(0);
  });

  it("get decodes error bodies into ApiError", async () => {
    const { client } = await load();
    mockFetch(jsonResponse(404, { error: { code: "not_found", message: "找不到資源" } }));
    const err = await failure(client.get("/api/v1/workbench"));
    expect(err).toBeInstanceOf(client.ApiError);
    expect(err.status).toBe(404);
    expect(err.code).toBe("not_found");
  });
  it("upload uses the same write headers, reports progress and keeps pending on 5xx", async () => {
    const { client, pending } = await load();
    const sent: Array<Record<string, unknown>> = [];
    class Xhr {
      headers: Record<string, string> = {};
      upload: { onprogress: ((e: unknown) => void) | null; onload: (() => void) | null } = { onprogress: null, onload: null };
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      onabort: (() => void) | null = null;
      status = 0;
      responseText = "";
      withCredentials = false;
      method = "";
      url = "";
      open(m: string, u: string) {
        this.method = m;
        this.url = u;
      }
      setRequestHeader(n: string, v: string) {
        this.headers[n] = v;
      }
      getResponseHeader(n: string) {
        return n === "Retry-After" ? "3" : null;
      }
      send(body: string) {
        sent.push({ xhr: this, body });
      }
    }
    vi.stubGlobal("XMLHttpRequest", Xhr);
    const progress: number[][] = [];
    let uploaded = false;
    const p = client.upload("POST", "/api/v1/backup/import", { format: "erpcrm-sim-backup" }, {
      onProgress: (l, t) => progress.push([l, t]),
      onUploaded: () => (uploaded = true),
    });
    expect(client.inflight.value).toBe(1);
    const xhr = sent[0].xhr as Xhr;
    expect(xhr.headers["x-csrf-token"]).toBe("csrf-token-1");
    expect(xhr.headers["If-Match-Version"]).toBe("7");
    expect(pending.readPending()?.key).toBe(xhr.headers["Idempotency-Key"]);
    xhr.upload.onprogress?.({ lengthComputable: true, loaded: 5, total: 10 });
    xhr.upload.onload?.();
    xhr.status = 503;
    xhr.responseText = JSON.stringify({ error: { code: "unavailable", message: "暫停服務" } });
    xhr.onload?.();
    const err = await failure(p);
    expect(err.status).toBe(503);
    expect(err.retryAfterMs).toBe(3000);
    expect(progress).toEqual([[5, 10]]);
    expect(uploaded).toBe(true);
    expect(pending.readPending()).not.toBeNull();
    expect(client.inflight.value).toBe(0);
  });
});
