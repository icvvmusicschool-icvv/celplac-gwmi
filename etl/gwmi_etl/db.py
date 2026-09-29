"""Acesso ao PostgreSQL.

O pipeline depende só do protocolo `Database`; a implementação de produção
usa psycopg 3 (COPY binário-texto para staging). Parâmetros no estilo
psycopg: %(nome)s.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterable, Iterator, Mapping, Protocol, Sequence


class Database(Protocol):
    def execute(self, sql: str, params: Mapping[str, Any] | None = None) -> None: ...
    def query(self, sql: str, params: Mapping[str, Any] | None = None) -> list[dict]: ...
    def scalar(self, sql: str, params: Mapping[str, Any] | None = None) -> Any: ...
    def copy_rows(self, table: str, columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> int: ...


class PsycopgDatabase:
    """Implementação psycopg 3. Autocommit por instrução; use `transaction()` para agrupar."""

    def __init__(self, dsn: str):
        import psycopg  # import tardio: o restante do pacote não depende do driver
        from psycopg.rows import dict_row

        self._psycopg = psycopg
        self.conn = psycopg.connect(dsn, autocommit=True, row_factory=dict_row)
        self.conn.execute("SET client_min_messages = warning")

    def execute(self, sql, params=None):
        self.conn.execute(sql, params or {})

    def query(self, sql, params=None):
        return list(self.conn.execute(sql, params or {}).fetchall())

    def scalar(self, sql, params=None):
        row = self.conn.execute(sql, params or {}).fetchone()
        return None if row is None else next(iter(row.values()))

    def copy_rows(self, table, columns, rows):
        n = 0
        cols = ", ".join(columns)
        with self.conn.cursor() as cur:
            with cur.copy(f"COPY {table} ({cols}) FROM STDIN") as cp:
                for r in rows:
                    cp.write_row(r)
                    n += 1
        return n

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self.conn.transaction():
            yield

    def close(self):
        self.conn.close()


def connect(dsn: str) -> PsycopgDatabase:
    return PsycopgDatabase(dsn)
