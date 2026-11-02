-- +goose Up
-- +goose StatementBegin
-- 銷售訂單：建立時預留庫存；paid／refunded 由 order.pay／cancel／return 流水累計。
-- seq 保留建立順序，快照與備份依此排序
CREATE TABLE sales_order (
    id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspace (id) ON DELETE CASCADE,
    learning_run_id TEXT,
    buyer_wallet_id UUID NOT NULL REFERENCES wallet (id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    total_minor BIGINT NOT NULL,
    paid_minor BIGINT NOT NULL DEFAULT 0,
    refunded_minor BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    seq BIGSERIAL NOT NULL
);

CREATE INDEX sales_order_workspace_seq_idx ON sales_order (workspace_id, seq);

-- 訂單品項：name、price_minor、cost_minor 是下單當時的商品快照，idx 為品項順序
CREATE TABLE order_line (
    id UUID PRIMARY KEY,
    order_id UUID NOT NULL REFERENCES sales_order (id) ON DELETE CASCADE,
    idx SMALLINT NOT NULL,
    product_id UUID NOT NULL REFERENCES product (id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    price_minor BIGINT NOT NULL,
    cost_minor BIGINT NOT NULL,
    quantity BIGINT NOT NULL,
    shipped_quantity BIGINT NOT NULL DEFAULT 0,
    returned_quantity BIGINT NOT NULL DEFAULT 0
);

CREATE INDEX order_line_order_idx ON order_line (order_id, idx);
CREATE INDEX order_line_product_idx ON order_line (product_id);

-- 出貨成本批次：出貨時依 FIFO 從商品成本層取出，id 為出貨順序；returned 為已退回件數
CREATE TABLE shipped_cost_lot (
    id BIGSERIAL PRIMARY KEY,
    line_id UUID NOT NULL REFERENCES order_line (id) ON DELETE CASCADE,
    quantity BIGINT NOT NULL,
    cost_minor BIGINT NOT NULL,
    returned BIGINT NOT NULL DEFAULT 0
);

CREATE INDEX shipped_cost_lot_line_idx ON shipped_cost_lot (line_id, id);
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP TABLE IF EXISTS shipped_cost_lot;
DROP TABLE IF EXISTS order_line;
DROP TABLE IF EXISTS sales_order;
-- +goose StatementEnd
