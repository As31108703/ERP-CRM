<script setup lang="ts">
import { computed } from "vue";
import { formatDateTime } from "../../lib/format";
import { findRow, list, recordName, statusKey, statusLabel, str, type Row } from "../../lib/records";
import DataSection from "../../ui/DataSection.vue";
import EmptyState from "../../ui/EmptyState.vue";
import type { FormField } from "../../ui/FormDialog.vue";
import RecordCard from "../../ui/RecordCard.vue";
import { API_V1, optionalText, useCommandForm, type FormValues } from "../shared/commandForm";
import { createBlocker, createSpec, options } from "../shared/createForms";
import CommandDialog from "../shared/CommandDialog.vue";
import PageHead from "../shared/PageHead.vue";
import { usePage } from "../shared/usePage";
import QuoteList from "./QuoteList.vue";
import { quoteSpec } from "./quoteForms";

const { store, ws, resetKey, rows, enabled, readiness, targetId, clearTarget, searchText } = usePage();
const form = useCommandForm();

const customers = computed(() => rows("customers"));
const contacts = computed(() => rows("contacts"));
const deals = computed(() => rows("deals"));
const cases = computed(() => rows("cases"));
const customerReason = computed(() => createBlocker("customer", ws.value));
const noCustomers = computed(() => customers.value.length === 0);

const DEAL_STAGES = ["new", "open", "won", "lost"];

const base = (collection: string, row?: Row, action = "") =>
  `${API_V1}/crm/${collection}${row ? `/${encodeURIComponent(row.id)}` : ""}${action ? `/${action}` : ""}`;

function customerName(row: Row): string {
  return recordName(findRow(ws.value, "customers", row.customer_id), "客戶");
}

function customerField(): FormField {
  return { name: "customer_id", label: "客戶", type: "select", required: true, options: options(customers.value, "客戶") };
}

function contactsOf(customer: Row): Row[] {
  return contacts.value.filter((c) => c.customer_id === customer.id);
}

/** 建立聯絡人／商機／案件：空白的選填欄位不送出。 */
function openCreate(kind: "contacts" | "deals" | "cases"): void {
  const titleField = kind === "contacts" ? "name" : "title";
  const fields: FormField[] =
    kind === "contacts"
      ? [
          { name: "name", label: "姓名", required: true },
          customerField(),
          { name: "email", label: "測試 Email", type: "email" },
          { name: "notes", label: "備註", type: "textarea" },
        ]
      : [
          { name: "title", label: kind === "deals" ? "商機名稱" : "案件名稱", required: true },
          customerField(),
          { name: "notes", label: kind === "deals" ? "需求備註" : "工作內容", type: "textarea" },
        ];
  form.open({
    title: { contacts: "新增聯絡人", deals: "新增商機", cases: "新增案件" }[kind],
    fields,
    build: (v: FormValues) => ({
      method: "POST",
      path: base(kind),
      body: optionalText({ [titleField]: v[titleField], customer_id: v.customer_id }, v, "email", "notes"),
    }),
  });
}

function openEditCustomer(c: Row): void {
  form.open({
    title: "編輯客戶",
    fields: [
      { name: "name", label: "客戶名稱", required: true },
      { name: "notes", label: "備註", type: "textarea" },
    ],
    initial: { name: str(c, "name"), notes: str(c, "notes") },
    build: (v) => ({ method: "PATCH", path: base("customers", c), body: { name: v.name, notes: v.notes } }),
  });
}

function openEditContact(c: Row): void {
  form.open({
    title: "編輯聯絡人",
    fields: [
      { name: "name", label: "姓名", required: true },
      customerField(),
      { name: "email", label: "測試 Email", type: "email" },
      { name: "notes", label: "備註", type: "textarea" },
    ],
    initial: { name: str(c, "name"), customer_id: str(c, "customer_id"), email: str(c, "email"), notes: str(c, "notes") },
    build: (v) => ({
      method: "PATCH",
      path: base("contacts", c),
      body: { name: v.name, customer_id: v.customer_id, email: v.email, notes: v.notes },
    }),
  });
}

function openEditDeal(d: Row): void {
  const current = str(d, "status");
  const stages = current && !DEAL_STAGES.includes(current) ? [...DEAL_STAGES, current] : DEAL_STAGES;
  form.open({
    title: "更新商機",
    fields: [
      { name: "title", label: "商機名稱", required: true },
      { name: "status", label: "階段", type: "select", required: true, options: stages.map((s) => ({ value: s, label: statusLabel(s) })) },
      { name: "lost_reason", label: "未成交原因（未成交時必填）", type: "textarea" },
    ],
    initial: { title: str(d, "title") || str(d, "name"), status: current || "new", lost_reason: str(d, "lost_reason") },
    build: (v) => {
      if (v.status === "lost" && !String(v.lost_reason ?? "").trim()) return "未成交時請填寫「未成交原因」。";
      return { method: "PATCH", path: base("deals", d), body: { title: v.title, status: v.status, lost_reason: v.lost_reason } };
    },
  });
}

function openFollowup(d: Row): void {
  form.open({
    title: "記錄跟進",
    fields: [{ name: "note", label: "本次聯繫與下一步", type: "textarea", required: true, maxlength: 2000 }],
    build: (v) => ({ method: "POST", path: base("deals", d, "followups"), body: { note: v.note } }),
  });
}

function openEditCase(c: Row): void {
  form.open({
    title: "編輯案件",
    fields: [
      { name: "title", label: "案件名稱", required: true },
      { name: "notes", label: "工作內容", type: "textarea" },
    ],
    initial: { title: str(c, "title") || str(c, "name"), notes: str(c, "notes") },
    build: (v) => ({ method: "PATCH", path: base("cases", c), body: { title: v.title, notes: v.notes } }),
  });
}

const latestFollowups = (d: Row) => list(d, "followups").slice(-3).reverse();
</script>

<template>
  <div class="mpage" data-testid="page-crm">
    <PageHead code="MODULE · CRM · REL" title="客戶與商機" lead="從客戶、聯絡人、商機跟進到案件與報價，保留同一條工作脈絡。">
      <button
        type="button"
        class="btn btn--primary"
        data-testid="create-customer"
        :disabled="Boolean(customerReason) || store.busy"
        @click="form.open(createSpec('customer', ws))"
      >
        新增客戶
      </button>
      <button type="button" class="btn" data-testid="create-contact" :disabled="noCustomers || store.busy" @click="openCreate('contacts')">
        新增聯絡人
      </button>
      <button type="button" class="btn" data-testid="create-deal" :disabled="noCustomers || store.busy" @click="openCreate('deals')">新增商機</button>
      <button type="button" class="btn" data-testid="create-case" :disabled="noCustomers || store.busy" @click="openCreate('cases')">新增案件</button>
      <span v-if="customerReason" class="phead__reason">{{ customerReason }}</span>
      <span v-else-if="noCustomers" class="phead__reason">先建立客戶，才能新增聯絡人、商機與案件</span>
    </PageHead>

    <EmptyState v-if="!enabled('crm')" title="尚未啟用此模組" text="請到設定頁切換產業範本或調整模組。" />
    <div v-else class="mpage__grid">
      <DataSection
        title="客戶"
        code="CUS-INDEX"
        :items="customers"
        :search-text="(c: Row) => searchText('customer', c, contactsOf(c).map((k) => recordName(k)))"
        :status-of="(c: Row) => statusKey('customer', c)"
        :status-label="statusLabel"
        :target-id="targetId('customer')"
        :reset-key="resetKey"
        empty-text="還沒有客戶。"
        @clear-target="clearTarget"
      >
        <template #item="{ item }">
          <RecordCard kind="customer" :row="item" :readiness="readiness('customer', item.id)">
            <template #title>{{ recordName(item, "客戶") }}</template>
            <p class="mpage__dim">{{ str(item, "notes") || "尚未填寫備註" }}</p>
            <ul v-if="contactsOf(item).length" class="mpage__lines">
              <li v-for="k in contactsOf(item)" :key="k.id">{{ recordName(k) }}{{ str(k, "email") ? ` · ${str(k, "email")}` : "" }}</li>
            </ul>
            <template #actions>
              <button type="button" class="btn btn--sm" :disabled="store.busy" @click="openEditCustomer(item)">編輯客戶</button>
            </template>
          </RecordCard>
        </template>
      </DataSection>

      <DataSection
        title="商機"
        code="DEAL-FLOW"
        :items="deals"
        :search-text="(d: Row) => searchText('deal', d, [customerName(d)])"
        :status-of="(d: Row) => statusKey('deal', d)"
        :status-label="statusLabel"
        :target-id="targetId('deal')"
        :reset-key="resetKey"
        empty-text="還沒有商機。"
        @clear-target="clearTarget"
      >
        <template #item="{ item }">
          <RecordCard kind="deal" :row="item" :readiness="readiness('deal', item.id)">
            <template #title>{{ recordName(item, "商機") }}</template>
            <template #meta>{{ customerName(item) }}</template>
            <p v-if="str(item, 'notes')">{{ str(item, "notes") }}</p>
            <p v-if="str(item, 'status') === 'lost' && str(item, 'lost_reason')" class="mpage__dim">未成交原因：{{ str(item, "lost_reason") }}</p>
            <ul v-if="latestFollowups(item).length" class="mpage__lines">
              <li v-for="f in latestFollowups(item)" :key="String(f.id)">
                <span>{{ str(f, "note") || "（無內容）" }}</span>
                <span class="mpage__dim num">{{ formatDateTime(f.created_at) }}</span>
              </li>
            </ul>
            <template #actions>
              <button type="button" class="btn btn--sm" :disabled="store.busy" @click="openEditDeal(item)">更新商機</button>
              <button type="button" class="btn btn--sm" :disabled="store.busy" @click="openFollowup(item)">記錄跟進</button>
            </template>
          </RecordCard>
        </template>
      </DataSection>

      <DataSection
        title="聯絡人"
        code="CNT-LINK"
        :items="contacts"
        :search-text="(c: Row) => searchText('contact', c, [customerName(c)])"
        :status-of="(c: Row) => statusKey('contact', c)"
        :status-label="statusLabel"
        :target-id="targetId('contact')"
        :reset-key="resetKey"
        empty-text="還沒有聯絡人。"
        @clear-target="clearTarget"
      >
        <template #item="{ item }">
          <RecordCard kind="contact" :row="item" :readiness="readiness('contact', item.id)">
            <template #title>{{ recordName(item, "聯絡人") }}</template>
            <template #meta>{{ customerName(item) }} · {{ str(item, "email") || "尚未填寫 Email" }}</template>
            <p v-if="str(item, 'notes')">{{ str(item, "notes") }}</p>
            <template #actions>
              <button type="button" class="btn btn--sm" :disabled="store.busy" @click="openEditContact(item)">編輯聯絡人</button>
            </template>
          </RecordCard>
        </template>
      </DataSection>

      <DataSection
        title="案件"
        code="CASE-FILE"
        :items="cases"
        :search-text="(c: Row) => searchText('case', c, [customerName(c)])"
        :status-of="(c: Row) => statusKey('case', c)"
        :status-label="statusLabel"
        :target-id="targetId('case')"
        :reset-key="resetKey"
        empty-text="還沒有案件。"
        @clear-target="clearTarget"
      >
        <template #item="{ item }">
          <RecordCard kind="case" :row="item" :readiness="readiness('case', item.id)">
            <template #title>{{ recordName(item, "案件") }}</template>
            <template #meta>{{ customerName(item) }}</template>
            <p v-if="str(item, 'notes')">{{ str(item, "notes") }}</p>
            <template #actions>
              <button type="button" class="btn btn--sm" :disabled="store.busy" @click="openEditCase(item)">編輯案件</button>
              <button type="button" class="btn btn--sm" :disabled="store.busy" @click="form.open(quoteSpec(ws, item.id))">建立報價</button>
            </template>
          </RecordCard>
        </template>
      </DataSection>
    </div>

    <QuoteList v-if="enabled('crm')" />
    <CommandDialog :form="form" />
  </div>
</template>

<style scoped src="../shared/page.css"></style>
