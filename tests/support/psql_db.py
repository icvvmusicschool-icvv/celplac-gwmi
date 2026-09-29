"""Implementação do protocolo Database via cliente `psql` — SOMENTE para testes
em ambientes sem driver Python (CI mínimo). Produção usa PsycopgDatabase.
"""
from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import tempfile
from datetime import date, datetime
from decimal import Decimal

_PARAM = re.compile(r"%\((\w+)\)s")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def literal(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float, Decimal)):
        return repr(v) if not isinstance(v, Decimal) else str(v)
    if isinstance(v, (date, datetime)):
        return f"'{v.isoformat()}'"
    if isinstance(v, (list, tuple)):
        if not v:
            return "'{}'"
        return "ARRAY[" + ", ".join(literal(x) for x in v) + "]"
    if isinstance(v, dict):
        v = json.dumps(v)
    return "'" + str(v).replace("'", "''") + "'"


def _conv(v):
    if isinstance(v, str) and _DATE.match(v):
        return date.fromisoformat(v)
    return v


class PsqlDatabase:
    def __init__(self, dsn: str):
        self.dsn = dsn

    def _run(self, sql: str, tuples_only=True) -> str:
        env = {**os.environ, "PGOPTIONS": "-c client_min_messages=warning"}
        args = ["psql", self.dsn, "-X", "-q", "-v", "ON_ERROR_STOP=1"] + (["-A", "-t"] if tuples_only else [])
        p = subprocess.run(args, input=sql, capture_output=True, text=True, env=env)
        if p.returncode != 0:
            raise RuntimeError(p.stderr.strip())
        return p.stdout

    @staticmethod
    def _bind(sql, params):
        return _PARAM.sub(lambda m: literal((params or {})[m.group(1)]), sql)

    def execute(self, sql, params=None):
        self._run(self._bind(sql, params) + ";\n")

    def query(self, sql, params=None):
        q = self._bind(sql, params).strip().rstrip(";")
        out = self._run(f"WITH _q AS ({q}) SELECT coalesce(json_agg(_q), '[]')::text FROM _q;\n").strip()
        rows = json.loads(out) if out else []
        return [{k: _conv(v) for k, v in r.items()} for r in rows]

    def scalar(self, sql, params=None):
        rows = self.query(sql, params)
        return None if not rows else next(iter(rows[0].values()))

    def copy_rows(self, table, columns, rows):
        n = 0
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            for r in rows:
                w.writerow(["" if x is None else (x.isoformat() if isinstance(x, date) else x) for x in r])
                n += 1
            path = f.name
        try:
            if n:
                self._run(f"\\copy {table} ({', '.join(columns)}) FROM '{path}' WITH (FORMAT csv)\n")
        finally:
            os.unlink(path)
        return n
