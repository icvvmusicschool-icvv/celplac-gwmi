"""Séries: Market Pulse, histórico, câmbio, macro."""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends, Query

from gwmi_core.analytics import pearson

from ..db import Repo
from ..deps import get_repo, months_ago
from ..envelope import envelope

router = APIRouter(tags=["series"])


@router.get("/pulse", summary="Market Pulse — valor, variação, período, fonte e histórico por indicador")
def pulse(history_months: int = Query(24, ge=6, le=120), repo: Repo = Depends(get_repo)):
    latest = repo.all("pulse")
    hist = repo.all("series_history", codes=[r["indicator_code"] for r in latest], since=months_ago(history_months))
    by = defaultdict(list)
    for h in hist:
        by[(h["indicator_code"], h["geo_iso3"])].append({"period": h["period"], "value": h["value"]})
    items = [{**r, "history": by.get((r["indicator_code"], r["geo_iso3"]), [])} for r in latest]
    return envelope(repo, items, kind="indicator",
                    notes=["Cor/leitura para o exportador (polarity) é hipótese, não fato."])


@router.get("/indicators", summary="Catálogo de indicadores com último valor")
def indicators(repo: Repo = Depends(get_repo)):
    rows = repo.all("indicators_list")
    return envelope(repo, rows, rows_for_meta=[r for r in rows if r.get("last_period")])


@router.get("/series/{indicator_code}", summary="Série temporal (mensal ou nativa)")
def series(indicator_code: str, geo: str = "WLD", frm: date | None = Query(None, alias="from"),
           to: date | None = None, native: bool = False, repo: Repo = Depends(get_repo)):
    p = {"code": indicator_code, "geo": geo.upper(), "from": frm or date(2000, 1, 1), "to": to or date.today()}
    rows = repo.all("series_native" if native else "series_monthly", **p)
    return envelope(repo, rows, period={"from": p["from"], "to": p["to"]})


@router.get("/latest", summary="Último valor, variações e média 5 anos por indicador")
def latest(category: str | None = None, geo: str | None = None, repo: Repo = Depends(get_repo)):
    return envelope(repo, repo.all("series_latest", category=category, geo=geo.upper() if geo else None), kind="indicator")


@router.get("/fx", summary="Câmbio: valor, variação, volatilidade anualizada 12m")
def fx(repo: Repo = Depends(get_repo)):
    return envelope(repo, repo.all("fx_stats"), kind="indicator")


@router.get("/correlation", summary="Correlação entre duas séries mensais (NÃO implica causalidade)")
def correlation(x: str = "FX_USD_BRL", x_geo: str = "BRA", y: str = "EXP_BR_VALUE", y_geo: str = "WLD",
                months: int = Query(60, ge=12, le=240), repo: Repo = Depends(get_repo)):
    rows = repo.all("correlation_pair", x_code=x, x_geo=x_geo, y_code=y, y_geo=y_geo, since=months_ago(months))
    r = pearson([float(a["x"]) for a in rows], [float(a["y"]) for a in rows])
    data = {"r": r, "n": len(rows), "points": rows}
    notes = ["Correlação ≠ causalidade: outras variáveis (preço, demanda, frete) mudam no mesmo período."]
    if r is None:
        notes.append("EVIDÊNCIA INSUFICIENTE — menos de 6 pares de observações.")
    return envelope(repo, data if rows else None, rows_for_meta=rows, kind="analysis", notes=notes)


@router.get("/macro", summary="Painel macro — último dado por país")
def macro(repo: Repo = Depends(get_repo)):
    return envelope(repo, repo.all("macro_latest"))
