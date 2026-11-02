#!/bin/sh

set -e

# Load environment variables from .env file
if [ -f ".env" ]; then
    echo "$(date "+%Y/%m/%d %H:%M:%S") INFO Loading environment variables from .env file"
    set -a  # automatically export all variables
    . ./.env
    set +a  # disable automatic export
else
    echo "$(date "+%Y/%m/%d %H:%M:%S") WARNING .env file not found, using existing environment variables"
fi

# libpq 的 key=value 連線字串：值一律用單引號包起來，並以反斜線跳脫值裡的反斜線與單引號，
# 密碼含空白、引號或等號時才不會被拆錯
pq_quote() {
    printf "'%s'" "$(printf '%s' "$1" | sed "s/[\\\\']/\\\\&/g")"
}

export GOOSE_DRIVER=postgres
GOOSE_DBSTRING="host=$(pq_quote "$DATABASE__HOST") port=$(pq_quote "$DATABASE__PORT")"
GOOSE_DBSTRING="$GOOSE_DBSTRING user=$(pq_quote "$DATABASE__USER")"
GOOSE_DBSTRING="$GOOSE_DBSTRING password=$(pq_quote "$DATABASE__PASSWORD")"
GOOSE_DBSTRING="$GOOSE_DBSTRING dbname=$(pq_quote "$DATABASE__NAME")"
export GOOSE_DBSTRING

migrate() {
    echo "$(date "+%Y/%m/%d %H:%M:%S") INFO Start to run database migration $*"
    goose -dir migrations "$@"
    echo "$(date "+%Y/%m/%d %H:%M:%S") INFO Complete migration"
}

migrate "$@"
