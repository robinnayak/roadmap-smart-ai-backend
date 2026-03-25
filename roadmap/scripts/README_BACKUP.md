# Database Backup

`scripts/backup_db.sh` creates a PostgreSQL SQL dump for the active database configuration.

## Usage

From `roadmap-smart-planner-backend/roadmap`:

```sh
chmod +x scripts/backup_db.sh
./scripts/backup_db.sh
```

## Supported environment inputs

- `DATABASE_URL`
- Or `DB_NAME`, `DB_USER`, `DB_HOST`, with optional `DB_PORT` and `DB_PASSWORD`

## Output

- Dumps are written to `backups/` by default.
- Override with `BACKUP_DIR=/custom/path`.

## Notes

- Local development can continue to use SQLite; this script is for PostgreSQL backups only.
- `pg_dump` must be installed in the environment where the script runs.
