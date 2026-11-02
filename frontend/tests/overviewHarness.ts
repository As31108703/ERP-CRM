import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { vi, type Mock } from "vitest";
import type { Component } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import type { Workbench, WorkspaceSnapshot } from "../src/api/types";
import { useWorkspaceStore } from "../src/stores/workspace";

/**
 * 掛載工作總覽元件：寫入 view／workbench，`store.run` 換成 spy，路由用記憶體歷程。
 * 必須在建立 ui store 之前先 push 好路由，元件 setup 時才拿得到 router。
 */
export async function mountOverview(
  component: Component,
  ws: WorkspaceSnapshot,
  opts: { workbench?: Workbench | null; props?: Record<string, unknown>; path?: string } = {},
) {
  setActivePinia(createPinia());
  const store = useWorkspaceStore();
  store.view = { workspace: ws, csrf: "c", version: ws.version };
  store.workbench = opts.workbench ?? null;
  store.loaded = true;
  const run: Mock = vi.fn(async () => ({ result: "new-id" }));
  store.run = run as unknown as typeof store.run;

  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/:rest(.*)*", component: { render: () => null } }],
  });
  await router.push(opts.path ?? "/overview");
  await router.isReady();

  const wrapper = mount(component, {
    props: opts.props ?? {},
    global: { plugins: [router], stubs: { teleport: true } },
    attachTo: document.body,
  });
  return { wrapper, run, store, router };
}

export function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}
