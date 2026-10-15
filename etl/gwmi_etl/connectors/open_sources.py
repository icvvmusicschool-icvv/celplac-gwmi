"""Fontes abertas das lacunas (migração 0019), agora no ETL Python.

Mesma lógica dos coletores de navegador (scripts/browser_macro_collect.js), para que a carga
automática produza exatamente os mesmos números:

  FRED a/a          INDPRO, TTLCONS → MACRO_IP_YOY / MACRO_CONSTRUCTION_YOY (EUA), % sobre o mesmo mês do ano anterior
  Eurostat          sts_inpr_m (B-D) e sts_copr_m (F), EU27_2020, PCH_SM, CA → MACRO_*_YOY (UE)
  NBS via DBnomics  A020101 (valor adicionado industrial, a/a) → MACRO_IP_YOY (China)
  INDEC             IPI manufacturero e ISAC, percent_change_a_year_ago × 100 → MACRO_*_YOY (Argentina)
  IBGE SIDRA        tabela simples de uma categoria (IPP 6903 → BR_IPP_WOOD)
  PEVS preço        tabela 291, v143 (mil R$) × 1000 ÷ v142 (m³), categoria 33257 → BR_LOG_PINUS_PRICE_IMPL

Cada conector separa `fetch` (baixa e guarda o original) de `parse_*` (função pura, testada com fixtures).
"""
from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path
from typing import Iterator

from ..pipeline import Job, http_download, parse_decimal

START = "2021-01"


def _ym(p: str) -> date:
    return date(int(p[:4]), int(p[5:7]), 1)


def _row(ind: str, geo: str, period: date, v: float | None) -> dict:
    return {"indicator_code": ind, "geo_iso3": geo, "period": period, "value": v,
            "obs_status": "A" if v is not None else "M"}


class _DownloadJob(Job):
    """Base: um endereço, um arquivo. Arquivo igual ao da última carga → 'unchanged'."""
    dataset = "series"
    skip_unchanged = True
    url: str = ""
    raw_name: str = "payload.json"

    def __init__(self, file: Path | None = None):
        self.file = Path(file) if file else None

    def raw_meta(self) -> dict:
        return {}

    def fetch(self, ctx):
        if self.file:
            return [ctx.register_raw(f"file://{self.file.resolve()}", self.file, None, self.raw_meta(), self.raw_name)]
        tmp, st = http_download(self.url, ctx.settings)
        try:
            return [ctx.register_raw(self.url, tmp, st, self.raw_meta(), self.raw_name)]
        finally:
            tmp.unlink(missing_ok=True)

    def rows(self, ctx, files):
        for f in files:
            yield from self.parse(Path(f).read_text(encoding="utf-8-sig"))

    def parse(self, text: str) -> Iterator[dict]:
        raise NotImplementedError


# ----------------------------------------------------------------------
# FRED — variação anual calculada sobre o nível (fredgraph.csv público)
# ----------------------------------------------------------------------
def parse_fred_yoy(text: str, indicator: str, geo: str, start: str = START) -> Iterator[dict]:
    rd = csv.reader(text.splitlines())
    header = next(rd, None)
    if not header or header[0].lower() not in ("observation_date", "date"):
        raise ValueError(f"CSV do FRED com cabeçalho inesperado: {header}")
    lvl: dict[str, float | None] = {}
    for r in rd:
        if r and r[0].strip():
            lvl[r[0].strip()[:7]] = parse_decimal(r[1] if len(r) > 1 else None)
    for p in sorted(lvl):
        if p < start:
            continue
        base = lvl.get(f"{int(p[:4]) - 1}{p[4:]}")
        v = lvl[p]
        yoy = round((v / base - 1) * 100, 4) if v is not None and base else None
        yield _row(indicator, geo, _ym(p), yoy)


class FredYoyJob(_DownloadJob):
    source_id = "fred"

    def __init__(self, series_id: str, indicator: str, geo: str = "USA", file: Path | None = None):
        super().__init__(file)
        self.series_id, self.indicator, self.geo = series_id, indicator, geo
        self.job_name = f"fred.{series_id.lower()}.yoy"
        self.url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd=2019-01-01"
        self.raw_name = f"fred_{series_id}.csv"

    def params(self):
        return {"series_id": self.series_id, "indicator": self.indicator, "geo": self.geo,
                "transform": "a/a % = (valor / valor do mesmo mês do ano anterior − 1) × 100, 4 casas"}

    def parse(self, text):
        return parse_fred_yoy(text, self.indicator, self.geo)


# ----------------------------------------------------------------------
# Eurostat — JSON-stat 2.0 (API de disseminação)
# ----------------------------------------------------------------------
def parse_eurostat(payload: dict, indicator: str, geo: str) -> Iterator[dict]:
    idx = payload["dimension"]["time"]["category"]["index"]
    vals = payload.get("value", {})
    for p, i in sorted(idx.items(), key=lambda kv: kv[1]):
        v = vals.get(str(i)) if isinstance(vals, dict) else (vals[i] if i < len(vals) else None)
        yield _row(indicator, geo, _ym(p), None if v is None else float(v))


class EurostatJob(_DownloadJob):
    source_id = "eurostat"

    def __init__(self, dataset: str, nace: str, indicator: str, geo: str = "EUU", file: Path | None = None):
        super().__init__(file)
        self.dataset_code, self.nace, self.indicator, self.geo = dataset, nace, indicator, geo
        self.job_name = f"eurostat.{dataset}.{nace.lower()}"
        self.url = (f"https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/{dataset}"
                    f"?geo=EU27_2020&unit=PCH_SM&s_adj=CA&nace_r2={nace}&indic_bt=PRD&sinceTimePeriod={START}")
        self.raw_name = f"eurostat_{dataset}.json"

    def params(self):
        return {"dataset": self.dataset_code, "nace_r2": self.nace, "unit": "PCH_SM", "s_adj": "CA",
                "indicator": self.indicator}

    def parse(self, text):
        return parse_eurostat(json.loads(text), self.indicator, self.geo)


# ----------------------------------------------------------------------
# DBnomics — espelho de estatísticas oficiais (NBS China)
# ----------------------------------------------------------------------
def parse_dbnomics(payload: dict, indicator: str, geo: str, start: str = START) -> Iterator[dict]:
    doc = payload["series"]["docs"][0]
    for p, v in zip(doc["period"], doc["value"]):
        if p < start:
            continue
        yield _row(indicator, geo, _ym(p), None if v in (None, "NA") else float(v))


class DbnomicsJob(_DownloadJob):
    def __init__(self, series_path: str, indicator: str, geo: str, source_id: str, file: Path | None = None):
        super().__init__(file)
        self.series_path, self.indicator, self.geo, self.source_id = series_path, indicator, geo, source_id
        self.job_name = f"dbnomics.{series_path.replace('/', '.').lower()}"
        self.url = f"https://api.db.nomics.world/v22/series/{series_path}?observations=1&format=json"
        self.raw_name = "dbnomics.json"

    def raw_meta(self):
        return {"mirror": "DBnomics"}

    def params(self):
        return {"series": self.series_path, "indicator": self.indicator, "geo": self.geo, "mirror": "DBnomics"}

    def parse(self, text):
        return parse_dbnomics(json.loads(text), self.indicator, self.geo)


# ----------------------------------------------------------------------
# datos.gob.ar — API de Series de Tiempo (INDEC); a/a calculada pela própria API
# ----------------------------------------------------------------------
def parse_datos_ar(payload: dict, indicator: str, geo: str = "ARG") -> Iterator[dict]:
    for p, v in payload.get("data", []):
        yield _row(indicator, geo, _ym(p), None if v is None else round(float(v) * 100, 4))


class DatosArJob(_DownloadJob):
    source_id = "indec"

    def __init__(self, series_id: str, indicator: str, geo: str = "ARG", file: Path | None = None):
        super().__init__(file)
        self.series_id, self.indicator, self.geo = series_id, indicator, geo
        self.job_name = f"indec.{indicator.lower()}"
        self.url = (f"https://apis.datos.gob.ar/series/api/series/?ids={series_id}"
                    f"&representation_mode=percent_change_a_year_ago&start_date={START}-01&format=json&limit=1000")
        self.raw_name = "datos_ar.json"

    def params(self):
        return {"series_id": self.series_id, "indicator": self.indicator, "representation": "percent_change_a_year_ago"}

    def parse(self, text):
        return parse_datos_ar(json.loads(text), self.indicator, self.geo)


# ----------------------------------------------------------------------
# IBGE SIDRA — tabela de uma única categoria (todas as linhas viram a série)
# ----------------------------------------------------------------------
def parse_sidra_single(payload: list, indicator: str, geo: str = "BRA") -> Iterator[dict]:
    if not payload:
        return
    header, rows = payload[0], payload[1:]
    pk = next((k[:-1] for k, lbl in header.items() if k.startswith("D") and k.endswith("N") and lbl in ("Mês", "Ano")), None)
    if pk is None:
        raise ValueError("cabeçalho SIDRA sem dimensão Mês/Ano")
    for r in rows:
        c = str(r[pk + "C"])
        per = date(int(c[:4]), int(c[4:6]) if len(c) == 6 else 1, 1)
        v = parse_decimal(r.get("V"))
        yield _row(indicator, geo, per, v)


class SidraSingleJob(_DownloadJob):
    source_id = "ibge_sidra"

    def __init__(self, path: str, indicator: str, file: Path | None = None):
        super().__init__(file)
        self.path, self.indicator = path, indicator
        self.job_name = f"ibge.sidra.{indicator.lower()}"
        self.url = "https://apisidra.ibge.gov.br/values" + path
        self.raw_name = "sidra.json"

    def params(self):
        return {"path": self.path, "indicator": self.indicator}

    def parse(self, text):
        return parse_sidra_single(json.loads(text), self.indicator)


IPP_WOOD_PATH = "/t/6903/n1/all/v/10008/p/all/c842/46625"
PIM_WOOD_PATH = "/t/8888/n1/all/v/12607/p/all/c544/129323"


# ----------------------------------------------------------------------
# PEVS — preço implícito da tora (valor ÷ quantidade)
# ----------------------------------------------------------------------
def parse_pevs_price(payload: list, indicator: str = "BR_LOG_PINUS_PRICE_IMPL", geo: str = "BRA",
                     first_year: int = 2013) -> Iterator[dict]:
    header, rows = payload[0], payload[1:]
    dims = {k[:-1]: lbl for k, lbl in header.items() if k.startswith("D") and k.endswith("N")}
    yk = next(k for k, l in dims.items() if l == "Ano")
    vk = next(k for k, l in dims.items() if l == "Variável")
    by: dict[str, dict[str, float | None]] = {}
    for r in rows:
        by.setdefault(str(r[yk + "C"]), {})[str(r[vk + "C"])] = parse_decimal(r.get("V"))
    for y in sorted(by):
        if int(y) < first_year:
            continue
        q, val = by[y].get("142"), by[y].get("143")
        v = round(val * 1000 / q, 2) if q and val is not None else None
        yield _row(indicator, geo, date(int(y), 1, 1), v)


class PevsPriceJob(_DownloadJob):
    source_id, job_name = "gwmi_calc", "ibge.pevs291.preco_implicito"
    url = "https://apisidra.ibge.gov.br/values/t/291/n1/all/v/142,143/p/all/c194/33257"
    raw_name = "pevs291_valor_quantidade.json"

    def params(self):
        return {"formula": "v143 (mil R$) × 1000 ÷ v142 (m³), c194=33257 (pinus, outras finalidades)"}

    def parse(self, text):
        return parse_pevs_price(json.loads(text))


# Conjunto padrão da carga automática
OPEN_JOBS = (
    lambda: FredYoyJob("INDPRO", "MACRO_IP_YOY"),
    lambda: FredYoyJob("TTLCONS", "MACRO_CONSTRUCTION_YOY"),
    lambda: EurostatJob("sts_inpr_m", "B-D", "MACRO_IP_YOY"),
    lambda: EurostatJob("sts_copr_m", "F", "MACRO_CONSTRUCTION_YOY"),
    lambda: DbnomicsJob("NBS/M_A0201/A020101", "MACRO_IP_YOY", "CHN", "nbs"),
    lambda: DatosArJob("453.1_SERIE_ORIGNAL_0_0_14_46", "MACRO_IP_YOY"),
    lambda: DatosArJob("33.2_ISAC_NIVELRAL_0_M_18_63", "MACRO_CONSTRUCTION_YOY"),
    lambda: SidraSingleJob(IPP_WOOD_PATH, "BR_IPP_WOOD"),
)
