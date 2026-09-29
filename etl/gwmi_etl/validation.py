"""Validação de linha (antes do staging). Regras de conjunto ficam em dq.rule (SQL).

Retorna None se a linha é válida, ou o motivo da rejeição.
Linha rejeitada não some: vai para dq.rejected_row com o conteúdo original.
"""
from __future__ import annotations

import re
from datetime import date

_NCM = re.compile(r"^\d{8}$")
_ISO3 = re.compile(r"^[A-Z]{3}$")


def validate_trade_row(r: dict) -> str | None:
    if r.get("_reject"):
        return r["_reject"]
    if r.get("flow") not in ("X", "M"):
        return "flow inválido"
    p = r.get("period")
    if not isinstance(p, date) or p.day != 1:
        return "período inválido (esperado 1º dia do mês)"
    if p.year < 1997 or p > date.today():
        return "período fora do intervalo plausível"
    if not _NCM.match(str(r.get("ncm8", ""))):
        return "NCM deve ter 8 dígitos"
    if r.get("code_scheme") not in ("comex", "iso3"):
        return "esquema de código de país inválido"
    if r.get("code_scheme") == "iso3" and not _ISO3.match(str(r.get("partner_code", ""))):
        return "parceiro ISO3 inválido"
    v = r.get("value_usd_fob")
    if v is None:
        return "valor FOB ausente"
    if v < 0:
        return "valor FOB negativo"
    for k in ("net_kg", "qty_stat"):
        if r.get(k) is not None and r[k] < 0:
            return f"{k} negativo"
    return None


def validate_series_row(r: dict) -> str | None:
    if r.get("_reject"):
        return r["_reject"]
    if not r.get("indicator_code"):
        return "indicador ausente"
    if not _ISO3.match(str(r.get("geo_iso3", ""))):
        return "geo ISO3 inválido"
    if not isinstance(r.get("period"), date):
        return "período inválido"
    if r.get("obs_status", "A") not in ("A", "P", "E", "M"):
        return "obs_status inválido"
    v = r.get("value")
    if v is not None and v != v:  # NaN
        return "valor NaN"
    if v is None and r.get("obs_status", "A") != "M":
        return "valor ausente sem obs_status='M'"
    return None
