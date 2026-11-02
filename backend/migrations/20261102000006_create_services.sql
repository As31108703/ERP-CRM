-- +goose Up
-- +goose StatementBegin
-- 服務：由案件建立（draft）→ confirmed → submitted ⇄ changes_requested → accepted；
-- paid_minor 由 service.pay 流水累計。title／source_case_title 為建立當時的案件標題快照，
-- price_source 為 explicit_simulation_input 或 industry_template_demo。
-- case_id、latest_delivery_id 不設外鍵，由一致性檢查回 404 record_missing／422 delivery_invalid。
-- seq 保留建立順序，快照與備份依此排序
CREATE TABLE service (
    id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspace (id) ON DELETE CASCADE,
    case_id UUID NOT NULL,
    title TEXT NOT NULL,
    source_case_title TEXT NOT NULL,
    price_source TEXT NOT NULL,
    amount_minor BIGINT NOT NULL,
    status TEXT NOT NULL,
    paid_minor BIGINT NOT NULL DEFAULT 0,
    latest_delivery_id UUID,
    legal_confirmation BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    seq BIGSERIAL NOT NULL
);

CREATE INDEX service_workspace_seq_idx ON service (workspace_id, seq);

-- 服務交付：每次交付新增一個版本，digest = 摘要({service_id, revision, artifact_ref})；
-- seq 為交付順序，最後一筆即最新版本
CREATE TABLE service_delivery (
    id UUID PRIMARY KEY,
    service_id UUID NOT NULL REFERENCES service (id) ON DELETE CASCADE,
    revision BIGINT NOT NULL,
    artifact_ref TEXT NOT NULL,
    digest TEXT NOT NULL,
    seq BIGSERIAL NOT NULL
);

CREATE INDEX service_delivery_service_seq_idx ON service_delivery (service_id, seq);
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP TABLE IF EXISTS service_delivery;
DROP TABLE IF EXISTS service;
-- +goose StatementEnd
