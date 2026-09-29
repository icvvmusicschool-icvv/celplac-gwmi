"""Fontes, qualidade, execuções e rastreabilidade ("De onde veio este número?")."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from ..db import Repo
from ..deps import get_repo
from ..envelope import envelope

router = APIRouter(tags=["meta"])


@router.get("/sources", summary="Catálogo de fontes com situação de integração")
def sources(repo: Repo = Depends(get_repo)):
    rows = repo.all("sources_list")
    return {"status": "ok", "data": rows, "meta": {"kind": "data", "is_simulated": False}}


@router.get("/quality", summary="Qualidade de dados por fonte e por regra")
def quality(repo: Repo = Depends(get_repo)):
    return {"status": "ok", "data": {"sources": repo.all("source_quality"), "rules": repo.all("rule_status")},
            "meta": {"kind": "data", "is_simulated": False}}


@router.get("/runs", summary="Execuções recentes do ETL")
def runs(limit: int = Query(50, le=500), repo: Repo = Depends(get_repo)):
    return {"status": "ok", "data": repo.all("runs_recent", limit=limit), "meta": {"kind": "data"}}


@router.get("/trace/trade/{trade_id}", summary="Linhagem de uma linha de comércio")
def trace_trade(trade_id: int, repo: Repo = Depends(get_repo)):
    row = repo.one("trace_trade", id=trade_id)
    if not row:
        raise HTTPException(404, "registro inexistente")
    return envelope(repo, row, kind="data")


@router.get("/trace/series/{indicator_code}", summary="Linhagem da observação de uma série")
def trace_series(indicator_code: str, geo: str = "WLD", period: date | None = None, repo: Repo = Depends(get_repo)):
    row = repo.one("trace_series", code=indicator_code, geo=geo.upper(), period=period)
    if not row:
        return envelope(repo, None, notes=["Nenhuma observação para este recorte."])
    return envelope(repo, row, kind=row["kind"])
