"""UN Comtrade (API v1) — comércio de outros países: concorrentes, importações
dos destinos e espelho das exportações brasileiras.

Endpoint: https://comtradeapi.un.org/data/v1/get/C/{M|A}/HS  (chave de assinatura)
Campos usados: period, reporterISO, partnerISO, cmdCode, flowCode,
fobvalue/primaryValue, netWgt, qty.
Observação: em importações o primaryValue é CIF; usamos fobvalue quando o
país o reporta e registramos a base em raw.ingestion.meta.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Iterator

from ..pipeline import Job, http_download, parse_decimal

_AGG = {"W00": "WLD", "EUR": "EUU"}


def parse_comtrade(payload: dict) -> Iterator[dict]:
    for d in payload.get("data", []):
        per = str(d["period"])
        period = date(int(per[:4]), int(per[4:6]) if len(per) >= 6 else 1, 1)
        flow = {"X": "X", "M": "M"}.get(str(d.get("flowCode", "")).upper()[:1])
        if flow is None:
            continue  # reexportações/reimportações ficam fora do recorte
        cmd = str(d["cmdCode"]).ljust(6, "0")[:6] + "00"
        rep = _AGG.get(d.get("reporterISO"), d.get("reporterISO"))
        par = _AGG.get(d.get("partnerISO"), d.get("partnerISO"))
        val = parse_decimal(d.get("fobvalue")) or parse_decimal(d.get("primaryValue"))
        yield {"flow": flow, "period": period, "reporter_code": rep or "XXX", "partner_code": par or "XXX",
               "code_scheme": "iso3", "ncm8": cmd, "value_usd_fob": val,
               "net_kg": parse_decimal(d.get("netWgt")), "qty_stat": parse_decimal(d.get("qty"))}


class ComtradeJob(Job):
    source_id, dataset = "comtrade", "trade"

    def __init__(self, reporter_m49: str, periods: str, cmd: str = "4412", partner_m49: str = "0",
                 flow: str = "M,X", freq: str = "M", file: Path | None = None):
        self.reporter, self.periods, self.cmd, self.partner, self.flow, self.freq, self.file = (
            reporter_m49, periods, cmd, partner_m49, flow, freq, file)
        self.job_name = f"comtrade.{freq.lower()}.{reporter_m49}"

    def params(self):
        return {"reporter": self.reporter, "periods": self.periods, "cmd": self.cmd, "partner": self.partner,
                "flow": self.flow, "freq": self.freq}

    def fetch(self, ctx):
        if self.file:
            return [ctx.register_raw(f"file://{Path(self.file).resolve()}", Path(self.file), None, {}, "comtrade.json")]
        if not ctx.settings.comtrade_key:
            raise RuntimeError("COMTRADE_API_KEY não configurada")
        url = ctx.settings.comtrade_url.format(freq=self.freq)
        p = {"reporterCode": self.reporter, "period": self.periods, "partnerCode": self.partner,
             "cmdCode": self.cmd, "flowCode": self.flow}
        tmp, st = http_download(url, ctx.settings, params=p,
                                headers={"Ocp-Apim-Subscription-Key": ctx.settings.comtrade_key})
        try:
            return [ctx.register_raw(f"{url}?{json.dumps(p)}", tmp, st, {"value_basis": "fobvalue|primaryValue"}, "comtrade.json")]
        finally:
            tmp.unlink(missing_ok=True)

    def rows(self, ctx, files):
        for f in files:
            yield from parse_comtrade(json.loads(Path(f).read_text(encoding="utf-8")))


# ----------------------------------------------------------------------
# API pública de pré-visualização (sem chave)
# Limites: 1 período por consulta, até 500 linhas, ~1 consulta/s (HTTP 429 acima disso).
# A resposta não traz reporterISO/partnerISO: o código M49 da Comtrade é convertido pelo
# arquivo de referência Reporters.json (a Comtrade usa códigos próprios, ex.: 842 = EUA, 251 = França).
# Filtros customsCode=C00, motCode=0, partner2Code=0 → só os totais (sem quebra por modal/regime).
# ----------------------------------------------------------------------
def parse_comtrade_preview(payload: dict, reporters: dict[int, str], exclude_reporters: tuple[str, ...] = ("BRA",),
                           partners: dict[int, str] | None = None) -> Iterator[dict]:
    partners = partners or {0: "WLD", 76: "BRA"}
    for d in payload.get("data", []):
        flow = {"X": "X", "M": "M"}.get(str(d.get("flowCode", "")).upper()[:1])
        if flow is None:
            continue
        rep = reporters.get(int(d["reporterCode"]))
        if rep in exclude_reporters:
            continue
        per = str(d["period"])
        period = date(int(per[:4]), int(per[4:6]) if len(per) >= 6 else 1, 1)
        par = partners.get(int(d.get("partnerCode", -1)))
        val = parse_decimal(d.get("fobvalue")) if flow == "X" else None
        val = val if val is not None else parse_decimal(d.get("primaryValue"))
        row = {"flow": flow, "period": period, "reporter_code": rep or f"#{d['reporterCode']}",
               "partner_code": par or "XXX", "code_scheme": "iso3",
               "ncm8": str(d["cmdCode"]).ljust(6, "0")[:6] + "00", "value_usd_fob": val,
               "net_kg": parse_decimal(d.get("netWgt")), "qty_stat": None}
        if rep is None:
            row["_reject"] = f"reportante Comtrade {d['reporterCode']} sem ISO3 em Reporters.json"
        yield row


class ComtradePreviewJob(Job):
    """Uma consulta = um período. freq A → period AAAA (grava 1º de janeiro = ano inteiro)."""
    source_id, dataset = "comtrade", "trade"

    def __init__(self, cmd: str, flow: str, period: str, freq: str = "A", partner: str = "0",
                 reporter: str | None = None, file: Path | None = None):
        self.cmd, self.flow, self.period, self.freq, self.partner, self.reporter, self.file = (
            cmd, flow, period, freq, partner, reporter, file)
        self.job_name = f"comtrade.preview.{freq.lower()}.{flow.lower()}.{cmd}"

    def params(self):
        return {"cmd": self.cmd, "flow": self.flow, "period": self.period, "freq": self.freq,
                "partner": self.partner, "reporter": self.reporter, "mode": "public preview (sem chave)"}

    def _query(self) -> dict:
        q = {"cmdCode": self.cmd, "flowCode": self.flow, "partnerCode": self.partner, "period": self.period,
             "customsCode": "C00", "motCode": "0", "partner2Code": "0"}
        if self.reporter:
            q["reporterCode"] = self.reporter
        return q

    def fetch(self, ctx):
        if self.file:
            return [ctx.register_raw(f"file://{Path(self.file).resolve()}", Path(self.file), None, {}, "comtrade_preview.json")]
        import time
        url = ctx.settings.comtrade_preview_url.format(freq=self.freq)
        for attempt in range(5):
            try:
                tmp, st = http_download(url, ctx.settings, params=self._query())
                break
            except Exception:  # 429: limite de ~1 consulta/s
                if attempt == 4:
                    raise
                time.sleep(2 + attempt * 2)
        try:
            from urllib.parse import urlencode
            return [ctx.register_raw(f"{url}?{urlencode(self._query())}", tmp, st,
                                     {"value_basis": "X: fobvalue; M: primaryValue (CIF quando o país reporta CIF)"},
                                     "comtrade_preview.json")]
        finally:
            tmp.unlink(missing_ok=True)

    def rows(self, ctx, files):
        reporters = _reporters(ctx)
        known = {r["iso3"] for r in ctx.db.query("SELECT iso3 FROM dw.dim_country")}
        for f in files:
            for r in parse_comtrade_preview(json.loads(Path(f).read_text(encoding="utf-8")), reporters):
                if "_reject" not in r and r["reporter_code"] not in known:
                    r["_reject"] = f"reportante {r['reporter_code']} sem país em dw.dim_country"
                yield r


_REPORTERS_CACHE: dict[int, str] | None = None


def _reporters(ctx) -> dict[int, str]:
    global _REPORTERS_CACHE
    if _REPORTERS_CACHE is None:
        tmp, _ = http_download(ctx.settings.comtrade_reporters_url, ctx.settings)
        try:
            res = json.loads(tmp.read_text(encoding="utf-8"))["results"]
        finally:
            tmp.unlink(missing_ok=True)
        _REPORTERS_CACHE = {int(r["reporterCode"]): r["reporterCodeIsoAlpha3"] for r in res if r.get("reporterCodeIsoAlpha3")}
    return _REPORTERS_CACHE
