"""Comércio: exportações, destinos, rotação, NCM, fluxos, concorrentes."""
from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query

from ..db import Repo
from ..deps import get_repo
from ..envelope import envelope

router = APIRouter(prefix="/trade", tags=["trade"])
Family = Literal["roundwood", "sawnwood", "veneer", "plywood", "lvl", "panels"]


def _prev_note(rows: list[dict]) -> list[str]:
    if rows and rows[0].get("prev_window_complete") is False:
        return ["EVIDÊNCIA INSUFICIENTE para variação: a janela anterior não tem todos os meses carregados."]
    return []


def _period(rows: list[dict], months: int) -> dict | None:
    return {"months": months, "end": rows[0].get("period_end")} if rows and rows[0].get("period_end") else {"months": months}


@router.get("/exports/summary", summary="Valor, volume, peso, preço médio — janela vs janela anterior")
def exports_summary(months: int = Query(12, ge=1, le=60), end: date | None = None, family: Family | None = None,
                    repo: Repo = Depends(get_repo)):
    rows = repo.all("exports_summary", end=end, months=months, family=family)
    data = rows[0] if rows and rows[0].get("value_usd") is not None else None
    return envelope(repo, data, rows_for_meta=rows, default_sources=("comexstat",), kind="indicator",
                    period=_period(rows, months), notes=_prev_note(rows))


@router.get("/exports/destinations", summary="Destinos identificados pelos dados — ranking, participação, tendência")
def destinations(months: int = Query(12, ge=1, le=60), end: date | None = None, family: Family | None = None,
                 repo: Repo = Depends(get_repo)):
    rows = repo.all("export_destinations", end=end, months=months, family=family)
    return envelope(repo, rows, default_sources=("comexstat",), kind="indicator", period={"months": months, "end": end},
                    notes=_prev_note(rows))


@router.get("/exports/shift", summary="Destination Shift — ganho/perda de participação, novos mercados, retração")
def shift(months: int = Query(12, ge=3, le=36), end: date | None = None, family: Family | None = None,
          min_delta: float = 0.002, repo: Repo = Depends(get_repo)):
    rows = repo.all("export_destinations", end=end, months=months, family=family)
    data = {
        "gaining": [r for r in rows if r["share_delta"] is not None and r["share_delta"] > min_delta and not r["is_new"]],
        "losing": [r for r in rows if r["share_delta"] is not None and r["share_delta"] < -min_delta],
        "new_markets": [r for r in rows if r["is_new"]],
        "contracting": [r for r in rows if r["value_var"] is not None and r["value_var"] < -0.03],
    }
    data["gaining"].sort(key=lambda r: -r["share_delta"])
    data["losing"].sort(key=lambda r: r["share_delta"])
    return envelope(repo, data if rows else None, rows_for_meta=rows, default_sources=("comexstat",), kind="indicator",
                    notes=[f"Limiar de variação de participação: {min_delta * 100:.1f} p.p."] + _prev_note(rows))


@router.get("/exports/by-hs6", summary="Exportações por SH6 / produto")
def by_hs6(months: int = Query(12, ge=1, le=60), end: date | None = None, repo: Repo = Depends(get_repo)):
    return envelope(repo, repo.all("exports_by_hs6", end=end, months=months), default_sources=("comexstat",))


@router.get("/flows", summary="Trade Flow — UF de origem → porto → região de destino")
def flows(months: int = Query(12, ge=1, le=60), end: date | None = None, repo: Repo = Depends(get_repo)):
    return envelope(repo, repo.all("export_flows", end=end, months=months), default_sources=("comexstat",))


@router.get("/monthly", summary="Série mensal de exportações (X) ou importações (M)")
def monthly(flow: Literal["X", "M"] = "X", family: Family | None = None, partner: str | None = None,
            repo: Repo = Depends(get_repo)):
    rows = repo.all("trade_monthly", family=family, partner=partner.upper() if partner else None, flow=flow)
    return envelope(repo, rows, default_sources=("comexstat",))


@router.get("/ncm", summary="Catálogo SH6/NCM da cadeia")
def ncm_catalog(repo: Repo = Depends(get_repo)):
    return {"status": "ok", "data": repo.all("ncm_catalog"), "meta": {"kind": "data", "is_simulated": False}}


@router.get("/ncm/search", summary="Pesquisa por NCM, produto, país, ano e mês")
def ncm_search(q: str | None = None, family: Family | None = None, partner: str | None = None,
               year: int | None = None, month: int | None = Query(None, ge=1, le=12),
               flow: Literal["X", "M"] = "X", repo: Repo = Depends(get_repo)):
    rows = repo.all("ncm_search", q=q, family=family, partner=partner.upper() if partner else None,
                    year=year, month=month, flow=flow)
    return envelope(repo, rows, default_sources=("comexstat",))


@router.get("/competitors", summary="Exportadores mundiais por SH4 — concorrentes identificados pelos dados")
def competitors(hs4: str = "4412", year: int | None = None, repo: Repo = Depends(get_repo)):
    rows = repo.all("competitors", hs4=hs4, year=year)
    return envelope(repo, rows, default_sources=("comtrade",), kind="indicator",
                    notes=["Padrão: último ano completo (12 meses)."])
