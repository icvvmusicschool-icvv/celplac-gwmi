#!/usr/bin/env bash
# Aplica as migrações pendentes em ordem, cada uma em uma transação.
# Uso: DATABASE_URL=postgresql://user:pass@host:5432/gwmi ./db/migrate.sh
set -euo pipefail
: "${DATABASE_URL:?defina DATABASE_URL}"
DIR="$(cd "$(dirname "$0")/migrations" && pwd)"
export PGOPTIONS="${PGOPTIONS:-} -c client_min_messages=warning"
PSQL=(psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -X -q)

"${PSQL[@]}" -c "CREATE SCHEMA IF NOT EXISTS meta;
  CREATE TABLE IF NOT EXISTS meta.schema_migrations (version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now(), checksum text NOT NULL);"

for f in "$DIR"/*.sql; do
  v="$(basename "$f" .sql)"
  sum="$(sha256sum "$f" | cut -d' ' -f1)"
  applied="$("${PSQL[@]}" -tA -c "SELECT checksum FROM meta.schema_migrations WHERE version = '$v'")"
  if [[ -n "$applied" ]]; then
    [[ "$applied" == "$sum" ]] || { echo "ERRO: $v já aplicada com checksum diferente — crie uma nova migração em vez de editar esta." >&2; exit 1; }
    continue
  fi
  echo "→ aplicando $v"
  "${PSQL[@]}" -1 -f "$f" -c "INSERT INTO meta.schema_migrations (version, checksum) VALUES ('$v', '$sum')"
done
echo "✓ migrações em dia"
