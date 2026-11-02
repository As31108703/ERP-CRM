-- +goose Up
-- +goose StatementBegin
-- CRM 通用紀錄：客戶、聯絡人、商機、案件，以及專案的任務與里程碑共用一張表，以 collection 區分。
-- customer_id／case_id 不設外鍵，由一致性檢查回 404 record_missing（參照須指向同工作區的對應集合）。
-- seq 保留建立順序，快照與備份依此排序
CREATE TABLE crm_record (
    id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspace (id) ON DELETE CASCADE,
    collection TEXT NOT NULL CHECK (
        collection IN ('customers', 'contacts', 'deals', 'cases', 'tasks', 'milestones')
    ),
    name TEXT,
    title TEXT,
    customer_id UUID,
    case_id UUID,
    status TEXT,
    notes TEXT,
    lost_reason TEXT,
    due_at TIMESTAMPTZ,
    email TEXT,
    phone TEXT,
    amount_minor BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    seq BIGSERIAL NOT NULL
);

CREATE INDEX crm_record_workspace_collection_seq_idx ON crm_record (workspace_id, collection, seq);

-- 商機跟進：seq 為新增順序
CREATE TABLE deal_followup (
    id UUID PRIMARY KEY,
    deal_id UUID NOT NULL REFERENCES crm_record (id) ON DELETE CASCADE,
    note TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    seq BIGSERIAL NOT NULL
);

CREATE INDEX deal_followup_deal_seq_idx ON deal_followup (deal_id, seq);

-- 報價：draft → issued（寫入摘要）→ simulated_confirmed；同案件新報價發出時舊的 issued 變 superseded
CREATE TABLE quote (
    id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspace (id) ON DELETE CASCADE,
    case_id UUID NOT NULL,
    amount_minor BIGINT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL,
    legal_confirmation BOOLEAN NOT NULL DEFAULT FALSE,
    digest TEXT,
    issued_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    seq BIGSERIAL NOT NULL
);

CREATE INDEX quote_workspace_seq_idx ON quote (workspace_id, seq);
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP TABLE IF EXISTS quote;
DROP TABLE IF EXISTS deal_followup;
DROP TABLE IF EXISTS crm_record;
-- +goose StatementEnd
