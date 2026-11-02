import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h } from "vue";
import CommandDialog from "../src/modules/shared/CommandDialog.vue";
import { useCommandForm } from "../src/modules/shared/commandForm";
import { DESIGN_PREVIEW_BLOCKED, PENDING_BLOCKED, useWorkspaceStore } from "../src/stores/workspace";
import { flush, workspace } from "./pageHarness";

afterEach(() => {
  document.body.innerHTML = "";
});

function setup() {
  setActivePinia(createPinia());
  const store = useWorkspaceStore();
  store.view = { workspace: workspace(), csrf: "c", version: 7 };
  store.loaded = true;
  const run = vi.fn(async () => ({ result: "ok" }));
  store.run = run as unknown as typeof store.run;
  let form!: ReturnType<typeof useCommandForm>;
  const Host = defineComponent({
    setup() {
      form = useCommandForm();
      return () => h(CommandDialog, { form });
    },
  });
  const wrapper = mount(Host, { global: { stubs: { teleport: true } }, attachTo: document.body });
  form.open({
    title: "模擬付款",
    fields: [],
    build: () => ({ method: "POST", path: "/api/v1/orders/o1/pay", body: {} }),
  });
  return { wrapper, store, run };
}

function submitButton(wrapper: ReturnType<typeof mount>) {
  return wrapper.get("[role=dialog] button[type=submit]");
}

describe("CommandDialog", () => {
  it("is blocked during a theme preview and an unconfirmed write, like other command buttons", async () => {
    const { wrapper, store, run } = setup();
    await flush();
    expect(submitButton(wrapper).attributes("disabled")).toBeUndefined();

    store.designPreview = true;
    await flush();
    expect(submitButton(wrapper).attributes("disabled")).toBeDefined();
    expect(wrapper.get("[role=dialog]").text()).toContain(DESIGN_PREVIEW_BLOCKED);
    await wrapper.get("[role=dialog] form").trigger("submit");
    await flush();
    expect(run).not.toHaveBeenCalled();

    store.designPreview = false;
    store.pending = { key: "k-12345678", method: "POST", path: "/api/v1/orders", body: {}, version: 7 };
    await flush();
    expect(submitButton(wrapper).attributes("disabled")).toBeDefined();
    expect(wrapper.get("[role=dialog]").text()).toContain(PENDING_BLOCKED);

    store.pending = null;
    await flush();
    expect(submitButton(wrapper).attributes("disabled")).toBeUndefined();
    await wrapper.get("[role=dialog] form").trigger("submit");
    await flush();
    expect(run).toHaveBeenCalledTimes(1);
  });
});
