"""Envelope padrão de resposta.

Todo endpoint devolve:
  { "status": "ok" | "DADO INDISPONÍVEL",
    "data": ...,
    "meta": { "is_simulated": bool, "sources": [...], "period": {...},
              "kind": "data|indicator|analysis|hypothesis|signal", "notes": [...], "generated_at": ... } }

Regras:
  * is_simulated é calculado a partir das linhas — nunca declarado à mão.
  * Se a API estiver configurada para não servir simulado (meta.setting api.allow_simulated=false)
    e o resultado for simulado, a resposta vira DADO INDISPONÍVEL.
  * Resultado vazio = DADO INDISPONÍVEL (nunca zero).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from .db import Repo

UNAVAILABLE = "DADO INDISPONÍVEL"


def _collect_sim(rows: Iterable[dict]) -> bool:
    return any(bool(r.get("is_simulated")) for r in rows if isinstance(r, dict))


def _collect_sources(rows: Iterable[dict]) -> set[str]:
    ids: set[str] = set()
    for r in rows:
        if not isinstance(r, dict):
            continue
        if r.get("source_id"):
            ids.add(r["source_id"])
        for s in r.get("sources") or []:
            ids.add(s)
    return ids


def allow_simulated(repo: Repo) -> bool:
    row = repo.one("api_settings")
    return True if not row else bool((row["value"] or {}).get("allow_simulated", True))


def envelope(repo: Repo, data: Any, *, rows_for_meta: list[dict] | None = None,
             default_sources: tuple[str, ...] = (), kind: str = "data", period: dict | None = None,
             notes: list[str] | None = None) -> dict:
    rows = rows_for_meta if rows_for_meta is not None else (data if isinstance(data, list) else [data] if data else [])
    sim = _collect_sim(rows)
    ids = _collect_sources(rows) or set(default_sources)
    if sim:
        ids.add("demo")
    notes = list(notes or [])
    status = "ok"
    empty = data is None or (isinstance(data, (list, dict)) and len(data) == 0)
    if sim and not allow_simulated(repo):
        data, status, sim = [], UNAVAILABLE, False
        notes.append("Somente dado simulado disponível e a API está configurada para não servi-lo.")
    elif empty:
        status = UNAVAILABLE
    if sim:
        notes.insert(0, "SIMULATED DATA — valores demonstrativos, não usar para decisão.")
    return {
        "status": status,
        "data": data,
        "meta": {
            "is_simulated": sim,
            "kind": kind,
            "sources": repo.all("sources_by_ids", ids=sorted(ids)) if ids else [],
            "period": period,
            "notes": notes,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }
