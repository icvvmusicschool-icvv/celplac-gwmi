"""Pool de conexões e carregamento das consultas nomeadas (app/sql/queries.sql)."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

SQL_FILE = Path(__file__).parent / "sql" / "queries.sql"
_NAME = re.compile(r"^--\s*name:\s*(\w+)\s*$", re.M)


@lru_cache
def queries() -> dict[str, str]:
    text = SQL_FILE.read_text(encoding="utf-8")
    parts = _NAME.split(text)
    out: dict[str, str] = {}
    for i in range(1, len(parts), 2):
        out[parts[i]] = parts[i + 1].strip().rstrip(";")
    return out


class Repo:
    """Executa consultas nomeadas. `pool` = psycopg_pool.ConnectionPool (dict_row)."""

    def __init__(self, pool):
        self.pool = pool

    def all(self, name: str, **params: Any) -> list[dict]:
        with self.pool.connection() as conn:
            return list(conn.execute(queries()[name], params).fetchall())

    def one(self, name: str, **params: Any) -> dict | None:
        rows = self.all(name, **params)
        return rows[0] if rows else None

    def write(self, name: str, **params: Any) -> dict | None:
        with self.pool.connection() as conn:
            with conn.transaction():
                cur = conn.execute(queries()[name], params)
                return cur.fetchone() if cur.description else None


def make_pool(dsn: str, min_size: int = 1, max_size: int = 10):
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    return ConnectionPool(dsn, min_size=min_size, max_size=max_size, open=True,
                          kwargs={"row_factory": dict_row, "autocommit": True})
