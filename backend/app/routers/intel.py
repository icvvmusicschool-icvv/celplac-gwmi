"""Geopolítica, notícias (News Impact Engine) e alertas."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query

from ..db import Repo
from ..deps import get_repo
from ..envelope import allow_simulated, envelope

router = APIRouter(tags=["intel"])


@router.get("/events", summary="Geopolitical Watch — evento, país, produto, rota, impacto potencial, confiança, evidência")
def events(category: str | None = None, country: str | None = None, limit: int = Query(100, le=500),
           repo: Repo = Depends(get_repo)):
    rows = repo.all("events", category=category, country=country.upper() if country else None,
                    allow_sim=allow_simulated(repo), limit=limit)
    return envelope(repo, rows, default_sources=("news",), kind="analysis",
                    notes=["Impacto potencial não é impacto medido. Sem evidência, o evento não é registrado."])


@router.get("/news", summary="Notícias classificadas: direto, indireto, contexto, monitoramento")
def news(impact_class: Literal["direto", "indireto", "contexto", "monitoramento"] | None = None,
         limit: int = Query(100, le=500), repo: Repo = Depends(get_repo)):
    rows = repo.all("news", impact_class=impact_class, allow_sim=allow_simulated(repo), limit=limit)
    return envelope(repo, rows, default_sources=("news",), kind="analysis")


@router.get("/alerts", summary="Alertas abertos")
def alerts(repo: Repo = Depends(get_repo)):
    return envelope(repo, repo.all("alerts_open", allow_sim=allow_simulated(repo)), kind="alert")
