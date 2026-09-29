"""CELPLAC GWMI — API (FastAPI). Documentação interativa em /docs."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from . import panel
from .auth import require_key
from .db import Repo, make_pool
from .routers import analytics, intel, meta, series, trade


@asynccontextmanager
async def lifespan(app: FastAPI):
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL não definida")
    # min_size=0: sem conexão ociosa aberta, o Neon pode hibernar quando ninguém usa
    pool = make_pool(dsn, min_size=0, max_size=int(os.environ.get("GWMI_POOL_MAX", "5")))
    app.state.repo = Repo(pool)
    yield
    pool.close()


app = FastAPI(
    title="CELPLAC Global Wood Market Intelligence — API",
    version="0.3.0",
    description=("Toda resposta traz `meta.is_simulated` e as fontes. Dado ausente = "
                 "`DADO INDISPONÍVEL`, nunca zero. Sinais não são previsões."),
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get("GWMI_CORS_ORIGINS", "http://localhost:5173").split(",")],
    allow_methods=["GET", "POST"],
    allow_headers=["X-API-Key", "Authorization", "Content-Type"],
)

KEY = [Depends(require_key)]
for r in (meta.router, series.router, trade.router, intel.router, analytics.router):
    app.include_router(r, prefix="/v1", dependencies=KEY)


@app.get("/v1/panel", tags=["painel"], dependencies=KEY,
         summary="Pacote de dados do painel (só dado real), em cache por 10 min")
def panel_data(request: Request, refresh: bool = Query(False, description="ignora o cache")):
    data = panel.CACHE.get(request.app.state.repo, force=refresh)
    return {"status": "ok", "data": data, "meta": {"is_simulated": False, "generated_at": data["ASOF"]}}


PAINEL = Path(__file__).parent / "static" / "painel.html"


@app.get("/", include_in_schema=False, response_class=HTMLResponse)
def painel_page():
    """Página do painel. Não traz dado nenhum: os números vêm de /v1/panel, que exige a chave."""
    return HTMLResponse(PAINEL.read_text(encoding="utf-8"),
                        headers={"Cache-Control": "no-cache", "X-Robots-Tag": "noindex",
                                 "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                                 "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
                                 "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'",
                                 "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff"})


@app.get("/health", tags=["meta"], summary="Processo no ar (sem chave); não consulta o banco")
def health():
    # Sem consulta ao banco: o health check do servidor não deve manter o Neon acordado o tempo todo.
    return {"status": "ok"}


@app.get("/health/db", tags=["meta"], summary="Banco respondendo (sem chave; não expõe dados)")
def health_db():
    with app.state.repo.pool.connection() as c:
        c.execute("SELECT 1")
    return {"status": "ok", "database": "ok"}
