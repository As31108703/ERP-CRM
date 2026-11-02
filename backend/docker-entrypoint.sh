#!/bin/sh

set -e

./scripts/migrate.sh up

exec "$@"
