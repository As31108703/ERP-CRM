-- +goose Up
-- +goose StatementBegin
-- 流程教學：每條路線每輪練習一列（run_id 為該輪的教學識別，訂單與工單以 learning_run_id 標記）。
-- 同一路線以最新建立的一列為目前這一輪；active 標記工作區目前選取的路線（至多一列為真）。
-- paused、scope、compact、quiz_choice、selected_step 是畫面偏好，更新時不增加工作區版本。
-- 與業務資料一樣，主鍵為 (workspace_id, id)，檢查點以複合外鍵參照同一工作區的那一輪。
-- 教學紀錄不進備份，隨工作區串聯刪除
CREATE TABLE learning_session (
    workspace_id UUID NOT NULL REFERENCES workspace (id) ON DELETE CASCADE,
    id UUID NOT NULL,
    path TEXT NOT NULL,
    run_id TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT FALSE,
    paused BOOLEAN NOT NULL DEFAULT FALSE,
    scope TEXT NOT NULL DEFAULT 'lesson',
    compact BOOLEAN NOT NULL DEFAULT FALSE,
    quiz_choice SMALLINT,
    selected_step TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    seq BIGSERIAL NOT NULL,
    PRIMARY KEY (workspace_id, id),
    UNIQUE (workspace_id, run_id)
);

CREATE INDEX learning_session_workspace_path_idx ON learning_session (workspace_id, path, seq);
CREATE UNIQUE INDEX learning_session_active_idx ON learning_session (workspace_id) WHERE active;

-- 教學檢查點：每一步執行成功時寫入一列，version 與 history 相同；
-- before／after 是執行前後的本輪讀值（各至多 12 列 {label, value}）
CREATE TABLE learning_checkpoint (
    workspace_id UUID NOT NULL REFERENCES workspace (id) ON DELETE CASCADE,
    session_id UUID NOT NULL,
    step_id TEXT NOT NULL,
    action TEXT NOT NULL,
    payload JSONB NOT NULL,
    result TEXT NOT NULL,
    version BIGINT NOT NULL,
    before JSONB NOT NULL,
    after JSONB NOT NULL,
    PRIMARY KEY (workspace_id, session_id, step_id),
    FOREIGN KEY (workspace_id, session_id) REFERENCES learning_session (workspace_id, id)
        ON DELETE CASCADE
);
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP TABLE IF EXISTS learning_checkpoint;
DROP TABLE IF EXISTS learning_session;
-- +goose StatementEnd
