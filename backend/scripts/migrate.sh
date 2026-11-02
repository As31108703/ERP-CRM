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

export GOOSE_DRIVER=postgres
export GOOSE_DBSTRING="host=$DATABASE__HOST port=$DATABASE__PORT user=$DATABASE__USER password=$DATABASE__PASSWORD dbname=$DATABASE__NAME"

migrate() {
    echo "$(date "+%Y/%m/%d %H:%M:%S") INFO Start to run database migration $@"
    goose -dir migrations $@
    echo "$(date "+%Y/%m/%d %H:%M:%S") INFO Complete migration"
}

migrate "$@"
