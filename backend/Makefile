.PHONY: run test lint format migrate

# 本機執行 API（需先啟動資料庫並完成 migration）
run:
	uv run python main.py

# 執行測試（需先 docker compose up -d db）
test:
	uv run pytest -v

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

# 例：make migrate cmd=up
migrate:
	./scripts/migrate.sh $(cmd)
