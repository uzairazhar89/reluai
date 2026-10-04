#!/bin/bash
# Runs once, when the PostgreSQL data volume is first initialised.
# Creates the least-privilege role the API and worker connect as. The schema owner
# (POSTGRES_USER) is used only by migrations; grants on its tables are applied by them.
set -euo pipefail

: "${RELUAI_APP_DB_PASSWORD:?RELUAI_APP_DB_PASSWORD must be set}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -v app_password="$RELUAI_APP_DB_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE reluai_app LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE',
              :'app_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'reluai_app') \gexec
GRANT CONNECT, TEMPORARY ON DATABASE :"DBNAME" TO reluai_app;
GRANT USAGE ON SCHEMA public TO reluai_app;
ALTER ROLE reluai_app SET statement_timeout = '15s';
ALTER ROLE reluai_app SET idle_in_transaction_session_timeout = '60s';
SQL
