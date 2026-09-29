"""Stub mínimo de `fastapi` para testar a lógica dos endpoints chamando as
funções diretamente (sem servidor HTTP) em ambientes sem FastAPI instalado.
Com FastAPI instalado, use tests com TestClient normalmente.
"""
import sys
import types


class HTTPException(Exception):
    def __init__(self, status_code, detail=None, headers=None):
        super().__init__(detail)
        self.status_code, self.detail = status_code, detail


class APIRouter:
    def __init__(self, *a, **k):
        self.routes = []

    def _deco(self, *a, **k):
        def wrap(fn):
            self.routes.append(fn)
            return fn
        return wrap

    get = post = put = delete = _deco


def Query(default=None, *a, **k):
    return default


def Depends(dep=None):
    return None


def install():
    if "fastapi" in sys.modules:
        return
    m = types.ModuleType("fastapi")
    m.APIRouter, m.Query, m.Depends, m.HTTPException = APIRouter, Query, Depends, HTTPException
    m.Request = object
    m.FastAPI = object
    sys.modules["fastapi"] = m


class _Cursor:
    def __init__(self, rows):
        self.rows, self.description = rows, (True if rows is not None else None)

    def fetchall(self):
        return self.rows or []

    def fetchone(self):
        return (self.rows or [None])[0]


class _Conn:
    def __init__(self, db):
        self.db = db

    def execute(self, sql, params=None):
        return _Cursor(self.db.query(sql, params or {}))

    def transaction(self):
        import contextlib
        return contextlib.nullcontext()


class PsqlPool:
    """Imita psycopg_pool.ConnectionPool sobre PsqlDatabase (testes)."""

    def __init__(self, db):
        self.db = db

    def connection(self):
        import contextlib
        return contextlib.nullcontext(_Conn(self.db))
