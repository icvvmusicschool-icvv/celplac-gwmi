"""Infra de testes: caminhos, criação de banco de teste e escolha do driver."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"
for p in (ROOT / "core", ROOT / "etl", ROOT / "backend", ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

# DSN do servidor (sem nome de banco) — ex.: postgresql://postgres@/?host=/tmp&port=5433
ADMIN_DSN = os.environ.get("GWMI_TEST_ADMIN_DSN", "postgresql://postgres@localhost:5432/postgres")
TEST_DB = os.environ.get("GWMI_TEST_DB", "gwmi_test")


def test_dsn() -> str:
    base, _, q = ADMIN_DSN.partition("?")
    base = base.rsplit("/", 1)[0] + "/" + TEST_DB
    return base + ("?" + q if q else "")


def fresh_database() -> str:
    """Recria o banco de teste e aplica todas as migrações com db/migrate.sh."""
    env = {**os.environ, "PGOPTIONS": "-c client_min_messages=warning"}
    subprocess.run(["psql", ADMIN_DSN, "-X", "-q", "-c", f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)"], check=True, env=env)
    subprocess.run(["psql", ADMIN_DSN, "-X", "-q", "-c", f"CREATE DATABASE {TEST_DB}"], check=True, env=env)
    subprocess.run([str(ROOT / "db" / "migrate.sh")], check=True, env={**env, "DATABASE_URL": test_dsn()},
                   stdout=subprocess.DEVNULL)
    return test_dsn()


def get_db(dsn: str):
    try:
        import psycopg  # noqa: F401
        from gwmi_etl.db import PsycopgDatabase
        return PsycopgDatabase(dsn)
    except ImportError:
        from support.psql_db import PsqlDatabase
        return PsqlDatabase(dsn)
