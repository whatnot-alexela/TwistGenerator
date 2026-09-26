#!/bin/sh
# Daily dump, fourteen kept. Run from cron on the host:
#   0 4 * * * cd /opt/twist && ./scripts/backup.sh >> backups/backup.log 2>&1
#
# The database holds the ratings the methodology is being researched with.
# Losing it loses the research, not just the service.
set -eu

mkdir -p backups
stamp=$(date +%Y-%m-%d)
docker compose exec -T postgres pg_dump -U twist twist | gzip > "backups/twist_${stamp}.sql.gz"

# Keep the newest fourteen.
ls -1t backups/twist_*.sql.gz | tail -n +15 | xargs -r rm --

echo "$(date -Is) backed up to backups/twist_${stamp}.sql.gz"
