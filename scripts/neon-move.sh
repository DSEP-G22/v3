#!/usr/bin/env bash
# Move the database to Singapore (ap-southeast-1).
#
# Neon cannot change a project's region, so the move is: create a new project in the region,
# copy the data into it, point .env at it. Every page in this product waits on at least one
# round trip, and from Colombo that is ~320 ms to Ohio against ~35 ms to Singapore.
#
#   1. In the Neon console: New project, region "Asia Pacific (Singapore)", Postgres 17.
#   2. Copy its pooled connection string.
#   3. OLD_DSN='postgresql://...us-east-2...' NEW_DSN='postgresql://...ap-southeast-1...' \
#        bash scripts/neon-move.sh
#   4. Put NEW_DSN in .env as NEON_KEY, then: docker compose up -d --force-recreate
#   5. Check the new round trip: uv run python scripts/neon-latency.py
#
# The old project is left untouched, so this is reversible until you delete it.
set -euo pipefail
: "${OLD_DSN:?set OLD_DSN to the current connection string}"
: "${NEW_DSN:?set NEW_DSN to the new Singapore connection string}"
IMG="${PG_IMAGE:-postgres:17-alpine}"

# Direct endpoints: pg_dump and pg_restore need session state the pooler does not keep.
OLD_DIRECT="${OLD_DSN/-pooler/}"
NEW_DIRECT="${NEW_DSN/-pooler/}"

echo "dumping the old database"
docker run --rm -i "$IMG" pg_dump --no-owner --no-privileges --no-acl --format=custom "$OLD_DIRECT" > /tmp/lanka-neon.dump
echo "dump is $(du -h /tmp/lanka-neon.dump | cut -f1)"

echo "restoring into the new one"
docker run --rm -i "$IMG" pg_restore --no-owner --no-privileges --clean --if-exists \
  --dbname "$NEW_DIRECT" < /tmp/lanka-neon.dump

echo "counting rows on both sides"
for dsn in "$OLD_DIRECT" "$NEW_DIRECT"; do
  docker run --rm "$IMG" psql "$dsn" -At -c \
    "select coalesce(sum(n_live_tup), 0) from pg_stat_user_tables"
done
echo "done. Put NEW_DSN in .env as NEON_KEY and recreate the stack."
