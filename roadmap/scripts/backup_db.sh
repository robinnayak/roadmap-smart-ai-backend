#!/usr/bin/env sh
set -eu

timestamp="$(date +%Y%m%d-%H%M%S)"
backup_dir="${BACKUP_DIR:-backups}"
mkdir -p "$backup_dir"

if [ -n "${DATABASE_URL:-}" ]; then
  output_path="$backup_dir/postgres-$timestamp.sql"
  pg_dump "$DATABASE_URL" > "$output_path"
elif [ -n "${DB_NAME:-}" ] && [ -n "${DB_USER:-}" ] && [ -n "${DB_HOST:-}" ]; then
  output_path="$backup_dir/postgres-$timestamp.sql"
  PGPASSWORD="${DB_PASSWORD:-}" pg_dump \
    --host="${DB_HOST}" \
    --port="${DB_PORT:-5432}" \
    --username="${DB_USER}" \
    --dbname="${DB_NAME}" \
    > "$output_path"
else
  echo "Database env vars are not set. Provide DATABASE_URL or DB_NAME/DB_USER/DB_HOST[/DB_PORT][/DB_PASSWORD]." >&2
  exit 1
fi

echo "Backup written to $output_path"
