-- +goose Up
-- +goose StatementBegin
-- 錢包：business、supplier、faucet 各一個（系統錢包），buyer 可以有多個。
-- seq 保留建立順序，快照與備份依此排序
CREATE TABLE wallet (
    id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspace (id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('business', 'supplier', 'faucet', 'buyer')),
    name TEXT NOT NULL,
    balance_minor BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    seq BIGSERIAL NOT NULL
);

CREATE INDEX wallet_workspace_seq_idx ON wallet (workspace_id, seq);

-- 複式帳本：每筆流水正好兩個分錄（見 ledger_entry），seq 為寫入順序
CREATE TABLE ledger (
    id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspace (id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    reference_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    seq BIGSERIAL NOT NULL
);

CREATE INDEX ledger_workspace_seq_idx ON ledger (workspace_id, seq);
CREATE INDEX ledger_workspace_reference_idx ON ledger (workspace_id, reference_id);

CREATE TABLE ledger_entry (
    ledger_id UUID NOT NULL REFERENCES ledger (id) ON DELETE CASCADE,
    idx SMALLINT NOT NULL,
    -- 錢包只隨工作區刪除；串聯刪除才不會在清除工作區時卡在外鍵檢查
    wallet_id UUID NOT NULL REFERENCES wallet (id) ON DELETE CASCADE,
    amount_minor BIGINT NOT NULL,
    PRIMARY KEY (ledger_id, idx)
);

CREATE INDEX ledger_entry_wallet_idx ON ledger_entry (wallet_id);

CREATE TABLE product (
    id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspace (id) ON DELETE CASCADE,
    sku TEXT NOT NULL,
    name TEXT NOT NULL,
    price_minor BIGINT NOT NULL,
    cost_minor BIGINT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    on_hand BIGINT NOT NULL DEFAULT 0,
    reserved BIGINT NOT NULL DEFAULT 0,
    stock_value_minor BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    seq BIGSERIAL NOT NULL
);

CREATE INDEX product_workspace_seq_idx ON product (workspace_id, seq);

-- 成本層：以 id 排序就是 FIFO 順序
CREATE TABLE product_lot (
    id BIGSERIAL PRIMARY KEY,
    product_id UUID NOT NULL REFERENCES product (id) ON DELETE CASCADE,
    quantity BIGINT NOT NULL,
    cost_minor BIGINT NOT NULL
);

CREATE INDEX product_lot_product_idx ON product_lot (product_id, id);

-- 採購入庫：以商品當時的成本進貨，total_minor = quantity * cost_minor
CREATE TABLE purchase (
    id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspace (id) ON DELETE CASCADE,
    product_id UUID NOT NULL REFERENCES product (id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    quantity BIGINT NOT NULL,
    cost_minor BIGINT NOT NULL,
    total_minor BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    seq BIGSERIAL NOT NULL
);

CREATE INDEX purchase_workspace_seq_idx ON purchase (workspace_id, seq);
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP TABLE IF EXISTS purchase;
DROP TABLE IF EXISTS product_lot;
DROP TABLE IF EXISTS product;
DROP TABLE IF EXISTS ledger_entry;
DROP TABLE IF EXISTS ledger;
DROP TABLE IF EXISTS wallet;
-- +goose StatementEnd
