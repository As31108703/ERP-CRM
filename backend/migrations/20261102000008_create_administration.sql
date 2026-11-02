-- +goose Up
-- +goose StatementBegin
-- 行政模組（A§1）。每張表以 workspace_id 串聯刪除；行政表彼此之間的參照設為 DEFERRABLE，
-- 匯入時可以任意順序寫入，參照正確性由命令管線的一致性檢查先行把關。
-- seq 保留寫入順序，快照依此輸出（同一命令建立的多筆資料 created_at 相同）。
CREATE TABLE adm_unit (
    id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspace (id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    parent_id UUID REFERENCES adm_unit (id) DEFERRABLE INITIALLY DEFERRED,
    active BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    seq BIGSERIAL NOT NULL
);
CREATE INDEX adm_unit_workspace_idx ON adm_unit (workspace_id, seq);

-- 假員工（虛構示範人物）
CREATE TABLE adm_staff (
    id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspace (id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    alias TEXT NOT NULL,
    unit_id UUID NOT NULL REFERENCES adm_unit (id) DEFERRABLE INITIALLY DEFERRED,
    role_label TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    seq BIGSERIAL NOT NULL
);
CREATE INDEX adm_staff_workspace_idx ON adm_staff (workspace_id, seq);

CREATE TABLE adm_shift (
    id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspace (id) ON DELETE CASCADE,
    staff_id UUID NOT NULL REFERENCES adm_staff (id) DEFERRABLE INITIALLY DEFERRED,
    unit_id UUID NOT NULL REFERENCES adm_unit (id) DEFERRABLE INITIALLY DEFERRED,
    start_at TIMESTAMPTZ NOT NULL,
    end_at TIMESTAMPTZ NOT NULL,
    break_minutes INT NOT NULL,
    note TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    seq BIGSERIAL NOT NULL
);
CREATE INDEX adm_shift_workspace_idx ON adm_shift (workspace_id, seq);

-- 手動輸入的實際出勤（非打卡）
CREATE TABLE adm_attendance (
    id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspace (id) ON DELETE CASCADE,
    staff_id UUID NOT NULL REFERENCES adm_staff (id) DEFERRABLE INITIALLY DEFERRED,
    unit_id UUID NOT NULL REFERENCES adm_unit (id) DEFERRABLE INITIALLY DEFERRED,
    start_at TIMESTAMPTZ NOT NULL,
    end_at TIMESTAMPTZ NOT NULL,
    break_minutes INT NOT NULL,
    note TEXT NOT NULL,
    voided BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    seq BIGSERIAL NOT NULL
);
CREATE INDEX adm_attendance_workspace_idx ON adm_attendance (workspace_id, seq);

CREATE TABLE adm_request (
    id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspace (id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    staff_id UUID REFERENCES adm_staff (id) DEFERRABLE INITIALLY DEFERRED,
    unit_id UUID NOT NULL REFERENCES adm_unit (id) DEFERRABLE INITIALLY DEFERRED,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    amount_minor BIGINT NOT NULL,
    currency TEXT NOT NULL DEFAULT 'SIM' CHECK (currency = 'SIM'),
    start_at TIMESTAMPTZ,
    end_at TIMESTAMPTZ,
    status TEXT NOT NULL,
    processing_note TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    seq BIGSERIAL NOT NULL
);
CREATE INDEX adm_request_workspace_idx ON adm_request (workspace_id, seq);

-- 申請的狀態紀錄，依 seq 排序；隨申請串聯刪除
CREATE TABLE adm_request_transition (
    request_id UUID NOT NULL REFERENCES adm_request (id) ON DELETE CASCADE,
    seq INT NOT NULL,
    status TEXT NOT NULL,
    at TIMESTAMPTZ NOT NULL,
    note TEXT NOT NULL,
    PRIMARY KEY (request_id, seq)
);

CREATE TABLE adm_equipment (
    id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspace (id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    unit_id UUID NOT NULL REFERENCES adm_unit (id) DEFERRABLE INITIALLY DEFERRED,
    state TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    seq BIGSERIAL NOT NULL
);
CREATE INDEX adm_equipment_workspace_idx ON adm_equipment (workspace_id, seq);

CREATE TABLE adm_reservation (
    id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspace (id) ON DELETE CASCADE,
    equipment_id UUID NOT NULL REFERENCES adm_equipment (id) DEFERRABLE INITIALLY DEFERRED,
    staff_id UUID NOT NULL REFERENCES adm_staff (id) DEFERRABLE INITIALLY DEFERRED,
    start_at TIMESTAMPTZ NOT NULL,
    end_at TIMESTAMPTZ NOT NULL,
    purpose TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    seq BIGSERIAL NOT NULL
);
CREATE INDEX adm_reservation_workspace_idx ON adm_reservation (workspace_id, seq);

-- unit_id 為 NULL 表示全體
CREATE TABLE adm_notice (
    id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspace (id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    unit_id UUID REFERENCES adm_unit (id) DEFERRABLE INITIALLY DEFERRED,
    pinned BOOLEAN NOT NULL,
    due_at TIMESTAMPTZ,
    archived BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    seq BIGSERIAL NOT NULL
);
CREATE INDEX adm_notice_workspace_idx ON adm_notice (workspace_id, seq);

-- 更正與封存紀錄：before／after 為整列快照；record_id 依 kind 指向不同資料表，不設外鍵
CREATE TABLE adm_change (
    id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspace (id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    record_id UUID NOT NULL,
    at TIMESTAMPTZ NOT NULL,
    reason TEXT NOT NULL,
    before JSONB NOT NULL,
    after JSONB NOT NULL,
    seq BIGSERIAL NOT NULL
);
CREATE INDEX adm_change_workspace_idx ON adm_change (workspace_id, seq);
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP TABLE IF EXISTS adm_change;
DROP TABLE IF EXISTS adm_notice;
DROP TABLE IF EXISTS adm_reservation;
DROP TABLE IF EXISTS adm_equipment;
DROP TABLE IF EXISTS adm_request_transition;
DROP TABLE IF EXISTS adm_request;
DROP TABLE IF EXISTS adm_attendance;
DROP TABLE IF EXISTS adm_shift;
DROP TABLE IF EXISTS adm_staff;
DROP TABLE IF EXISTS adm_unit;
-- +goose StatementEnd
