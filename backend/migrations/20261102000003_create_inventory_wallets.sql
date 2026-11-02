-- +goose Up
-- +goose StatementBegin
-- 業務資料的識別碼以工作區為範圍：主鍵是 (workspace_id, id)，子表也帶 workspace_id，
-- 以複合外鍵 (workspace_id, x_id) 參照同一工作區的上層資料。匯入時沿用備份中的 id，
-- 同一份備份因此可以匯入多個工作區，也不會透露其他工作區是否有相同的 id。

-- 錢包：business、supplier、faucet 各一個（系統錢包），buyer 可以有多個。
-- seq 保留建立順序，快照與備份依此排序
CREATE TABLE wallet (
    workspace_id UUID NOT NULL REFERENCES workspace (id) ON DELETE CASCADE,
    id UUID NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('business', 'supplier', 'faucet', 'buyer')),
    name TEXT NOT NULL,
    balance_minor BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    seq BIGSERIAL NOT NULL,
    PRIMARY KEY (workspace_id, id)
);

CREATE INDEX wallet_workspace_seq_idx ON wallet (workspace_id, seq);

-- 複式帳本：每筆流水正好兩個分錄（見 ledger_entry），seq 為寫入順序
CREATE TABLE ledger (
    workspace_id UUID NOT NULL REFERENCES workspace (id) ON DELETE CASCADE,
    id UUID NOT NULL,
    kind TEXT NOT NULL,
    reference_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    seq BIGSERIAL NOT NULL,
    PRIMARY KEY (workspace_id, id)
);

CREATE INDEX ledger_workspace_seq_idx ON ledger (workspace_id, seq);
CREATE INDEX ledger_workspace_reference_idx ON ledger (workspace_id, reference_id);

CREATE TABLE ledger_entry (
    workspace_id UUID NOT NULL REFERENCES workspace (id) ON DELETE CASCADE,
    ledger_id UUID NOT NULL,
    idx SMALLINT NOT NULL,
    wallet_id UUID NOT NULL,
    amount_minor BIGINT NOT NULL,
    PRIMARY KEY (workspace_id, ledger_id, idx),
    FOREIGN KEY (workspace_id, ledger_id) REFERENCES ledger (workspace_id, id) ON DELETE CASCADE,
    -- 錢包只隨工作區刪除；串聯刪除才不會在清除工作區時卡在外鍵檢查
    FOREIGN KEY (workspace_id, wallet_id) REFERENCES wallet (workspace_id, id) ON DELETE CASCADE
);

CREATE INDEX ledger_entry_wallet_idx ON ledger_entry (workspace_id, wallet_id);

CREATE TABLE product (
    workspace_id UUID NOT NULL REFERENCES workspace (id) ON DELETE CASCADE,
    id UUID NOT NULL,
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
    seq BIGSERIAL NOT NULL,
    PRIMARY KEY (workspace_id, id)
);

CREATE INDEX product_workspace_seq_idx ON product (workspace_id, seq);

-- 成本層：以 id 排序就是 FIFO 順序（id 由資料庫產生，不進備份）
CREATE TABLE product_lot (
    id BIGSERIAL PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspace (id) ON DELETE CASCADE,
    product_id UUID NOT NULL,
    quantity BIGINT NOT NULL,
    cost_minor BIGINT NOT NULL,
    FOREIGN KEY (workspace_id, product_id) REFERENCES product (workspace_id, id) ON DELETE CASCADE
);

CREATE INDEX product_lot_product_idx ON product_lot (workspace_id, product_id, id);

-- 採購入庫：以商品當時的成本進貨，total_minor = quantity * cost_minor
CREATE TABLE purchase (
    workspace_id UUID NOT NULL REFERENCES workspace (id) ON DELETE CASCADE,
    id UUID NOT NULL,
    product_id UUID NOT NULL,
    name TEXT NOT NULL,
    quantity BIGINT NOT NULL,
    cost_minor BIGINT NOT NULL,
    total_minor BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    seq BIGSERIAL NOT NULL,
    PRIMARY KEY (workspace_id, id),
    FOREIGN KEY (workspace_id, product_id) REFERENCES product (workspace_id, id) ON DELETE CASCADE
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
