-- +goose Up
-- +goose StatementBegin
-- 每個瀏覽器一筆 session；cookie 權杖只存 sha256，版本號與速率視窗也放在這裡，
-- 寫入時以 SELECT … FOR UPDATE 鎖住這一列，同一工作區的命令因此依序執行
CREATE TABLE workspace_session (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    token_hash CHAR(64) NOT NULL UNIQUE,
    csrf CHAR(64) NOT NULL,
    version INT NOT NULL DEFAULT 0,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    rate_start TIMESTAMPTZ NOT NULL DEFAULT now(),
    rate_count INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 保留排程依最後存取時間清除過期 session
CREATE INDEX workspace_session_last_seen_at_idx ON workspace_session (last_seen_at);

CREATE TABLE workspace (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL UNIQUE REFERENCES workspace_session (id) ON DELETE CASCADE,
    generation_id TEXT NOT NULL,
    industry TEXT NOT NULL,
    company_name VARCHAR(100) NOT NULL,
    modules TEXT[] NOT NULL,
    template_version INT NOT NULL,
    schema_version INT NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 冪等收據：Idempotency-Key 綁定請求摘要；seq 保留寫入順序，修剪時保留最近的收據
CREATE TABLE receipt (
    session_id UUID NOT NULL REFERENCES workspace_session (id) ON DELETE CASCADE,
    key VARCHAR(100) NOT NULL,
    hash CHAR(64) NOT NULL,
    expected_version INT NOT NULL,
    version INT NOT NULL,
    action TEXT NOT NULL,
    result TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    seq BIGSERIAL NOT NULL,
    PRIMARY KEY (session_id, key)
);

CREATE INDEX receipt_session_seq_idx ON receipt (session_id, seq);

-- 操作歷史：每個成功的業務命令一筆。id 以工作區為範圍（匯入時沿用備份的 id，
-- 同一份備份可以匯入多個工作區）
CREATE TABLE history (
    workspace_id UUID NOT NULL REFERENCES workspace (id) ON DELETE CASCADE,
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    action TEXT NOT NULL,
    result TEXT,
    version INT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, id)
);

CREATE INDEX history_workspace_version_idx ON history (workspace_id, version);
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP TABLE IF EXISTS history;
DROP TABLE IF EXISTS receipt;
DROP TABLE IF EXISTS workspace;
DROP TABLE IF EXISTS workspace_session;
-- +goose StatementEnd
