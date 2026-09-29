"""Sinais (early warning), ciclo de mercado e índice composto configurável."""
from __future__ import annotations

import json
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from gwmi_core.analytics import composite_index

from ..db import Repo
from ..deps import get_repo
from ..envelope import envelope

router = APIRouter(tags=["analytics"])


@router.get("/signals", summary="Early Warning — SINAL / INDICAÇÃO / SEM SINAL / EVIDÊNCIA INSUFICIENTE")
def signals(repo: Repo = Depends(get_repo)):
    return envelope(repo, repo.all("signals_latest"), default_sources=("gwmi_calc",), kind="signal",
                    notes=["Sinal não é previsão garantida. Condições e valores observados em `detail`."])


@router.get("/cycle", summary="Market Cycle — nível vs média 5a × momentum 6m (regra configurável)")
def cycle(momentum_threshold: float | None = None, repo: Repo = Depends(get_repo)):
    return envelope(repo, repo.all("market_cycle", threshold=momentum_threshold), kind="indicator",
                    notes=["Posicionamento por regra, não previsão."])


class Component(BaseModel):
    indicator: str
    geo: str = "WLD"
    weight: float = Field(ge=0, le=100)
    invert: bool = False


class IndexRequest(BaseModel):
    config_id: int | None = None
    components: list[Component] | None = None
    save_as: str | None = Field(None, description="se informado, registra a configuração em intel.index_config")
    created_by: str = "api"


@router.post("/index", summary="CELPLAC Global Wood Market Index — cálculo com pesos configuráveis")
def index(req: IndexRequest, repo: Repo = Depends(get_repo)):
    if req.components:
        comps = [c.model_dump() for c in req.components]
        config = {"config_id": None, "name": "ad hoc"}
    else:
        cfg = repo.one("index_config", config_id=req.config_id)
        if not cfg:
            raise HTTPException(404, "configuração de índice não encontrada")
        comps = cfg["components"] if isinstance(cfg["components"], list) else json.loads(cfg["components"])
        config = {"config_id": cfg["config_id"], "name": cfg["name"], "note": cfg.get("note")}
    rows = repo.all("index_series", codes=[c["indicator"] for c in comps], geos=[c.get("geo", "WLD") for c in comps])
    series, sim = defaultdict(list), False
    for r in rows:
        series[(r["indicator_code"], r["geo_iso3"].strip())].append((r["period"], float(r["value"])))
        sim = sim or bool(r["is_simulated"])
    res = composite_index(comps, series)
    if req.save_as and req.components:
        config.update(repo.write("index_config_insert", name=req.save_as, components=json.dumps(comps),
                                 created_by=req.created_by, note="criada via API") or {})
    data = {"config": config, "periods": res.periods, "values": res.values, "components_used": res.used,
            "components_missing": res.missing, "total_weight": res.total_weight} if res.values else None
    return envelope(repo, data, rows_for_meta=[{"is_simulated": sim}], default_sources=("gwmi_calc",), kind="indicator",
                    notes=["Pesos não definitivos — sem estudo estatístico ainda.",
                           "Índice só nos meses em que todos os componentes usados têm dado."])
