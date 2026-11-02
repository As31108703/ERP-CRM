-- +goose Up
-- +goose StatementBegin
-- 銷售訂單：建立時預留庫存；paid／refunded 由 order.pay／cancel／return 流水累計。
-- 主鍵 (workspace_id, id)，品項與出貨成本批次以複合外鍵參照同一工作區的上層資料。
-- seq 保留建立順序，快照與備份依此排序
CREATE TABLE sales_order (
    workspace_id UUID NOT NULL REFERENCES workspace (id) ON DELETE CASCADE,
    id UUID NOT NULL,
    learning_run_id TEXT,
    buyer_wallet_id UUID NOT NULL,
    status TEXT NOT NULL,
    total_minor BIGINT NOT NULL,
    paid_minor BIGINT NOT NULL DEFAULT 0,
    refunded_minor BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    seq BIGSERIAL NOT NULL,
    PRIMARY KEY (workspace_id, id),
    FOREIGN KEY (workspace_id, buyer_wallet_id) REFERENCES wallet (workspace_id, id)
        ON DELETE CASCADE
);

CREATE INDEX sales_order_workspace_seq_idx ON sales_order (workspace_id, seq);

-- 訂單品項：name、price_minor、cost_minor 是下單當時的商品快照，idx 為品項順序
CREATE TABLE order_line (
    workspace_id UUID NOT NULL REFERENCES workspace (id) ON DELETE CASCADE,
    id UUID NOT NULL,
    order_id UUID NOT NULL,
    idx SMALLINT NOT NULL,
    product_id UUID NOT NULL,
    name TEXT NOT NULL,
    price_minor BIGINT NOT NULL,
    cost_minor BIGINT NOT NULL,
    quantity BIGINT NOT NULL,
    shipped_quantity BIGINT NOT NULL DEFAULT 0,
    returned_quantity BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (workspace_id, id),
    FOREIGN KEY (workspace_id, order_id) REFERENCES sales_order (workspace_id, id)
        ON DELETE CASCADE,
    FOREIGN KEY (workspace_id, product_id) REFERENCES product (workspace_id, id) ON DELETE CASCADE
);

CREATE INDEX order_line_order_idx ON order_line (workspace_id, order_id, idx);
CREATE INDEX order_line_product_idx ON order_line (workspace_id, product_id);

-- 出貨成本批次：出貨時依 FIFO 從商品成本層取出，id 為出貨順序（由資料庫產生，不進備份）；
-- returned 為已退回件數
CREATE TABLE shipped_cost_lot (
    id BIGSERIAL PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspace (id) ON DELETE CASCADE,
    line_id UUID NOT NULL,
    quantity BIGINT NOT NULL,
    cost_minor BIGINT NOT NULL,
    returned BIGINT NOT NULL DEFAULT 0,
    FOREIGN KEY (workspace_id, line_id) REFERENCES order_line (workspace_id, id) ON DELETE CASCADE
);

CREATE INDEX shipped_cost_lot_line_idx ON shipped_cost_lot (workspace_id, line_id, id);
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP TABLE IF EXISTS shipped_cost_lot;
DROP TABLE IF EXISTS order_line;
DROP TABLE IF EXISTS sales_order;
-- +goose StatementEnd
