-- +goose Up
-- +goose StatementBegin
-- BOM：不可變，同一成品每次建立都是新版本（revision = 該成品既有 BOM 數 + 1）。
-- product_id、bom_component.product_id 不設外鍵，由一致性檢查回 404 record_missing。
-- seq 保留建立順序，快照與備份依此排序
CREATE TABLE bom (
    id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspace (id) ON DELETE CASCADE,
    product_id UUID NOT NULL,
    revision BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    seq BIGSERIAL NOT NULL
);

CREATE INDEX bom_workspace_seq_idx ON bom (workspace_id, seq);

-- BOM 材料：idx 為材料在 BOM 中的順序（1..30 筆）
CREATE TABLE bom_component (
    bom_id UUID NOT NULL REFERENCES bom (id) ON DELETE CASCADE,
    idx SMALLINT NOT NULL,
    product_id UUID NOT NULL,
    quantity BIGINT NOT NULL,
    PRIMARY KEY (bom_id, idx)
);

-- 工單：planned → reserved → started → completed，或取消（cancelled）。
-- bom_snapshot 為建立當時 BOM 的完整複本，必須與 BOM 相同；
-- actual_cost_minor 只在完工時寫入。bom_id 不設外鍵，由一致性檢查回 404 record_missing
CREATE TABLE work_order (
    id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspace (id) ON DELETE CASCADE,
    learning_run_id TEXT,
    bom_id UUID NOT NULL,
    bom_snapshot JSONB NOT NULL,
    quantity BIGINT NOT NULL,
    status TEXT NOT NULL,
    actual_cost_minor BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    seq BIGSERIAL NOT NULL
);

CREATE INDEX work_order_workspace_seq_idx ON work_order (workspace_id, seq);

-- 完工時依 FIFO 耗用的材料成本層；id 由小到大是耗用順序
CREATE TABLE consumed_material_lot (
    id BIGSERIAL PRIMARY KEY,
    work_order_id UUID NOT NULL REFERENCES work_order (id) ON DELETE CASCADE,
    product_id UUID NOT NULL,
    quantity BIGINT NOT NULL,
    cost_minor BIGINT NOT NULL
);

CREATE INDEX consumed_material_lot_work_order_idx ON consumed_material_lot (work_order_id, id);
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP TABLE IF EXISTS consumed_material_lot;
DROP TABLE IF EXISTS work_order;
DROP TABLE IF EXISTS bom_component;
DROP TABLE IF EXISTS bom;
-- +goose StatementEnd
