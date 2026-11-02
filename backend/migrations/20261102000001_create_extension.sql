-- +goose Up
-- +goose StatementBegin
-- gen_random_uuid()、digest() 等 UUID 與雜湊函式
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP EXTENSION IF EXISTS "pgcrypto";
-- +goose StatementEnd
