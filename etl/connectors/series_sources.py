"""Conectores de séries temporais: BCB PTAX, FRED, IBGE SIDRA, FAOSTAT e CSV manual.

Cada conector separa `fetch` (baixa e guarda o payload original) de
`parse_*` (função pura, testável com fixtures).
"""
from __future__ import annotations

import csv
import json
from datetime import date, datetime
from pathlib import Path
from collections import defaultdict
from typing import Iterable, Iterator
from urllib.parse import quote

from ..pipeline import Job, RunContext, http_download, parse_decimal


# ----------------------------------------------------------------------
# BCB — PTAX (Olinda OData). Mantém apenas o boletim de fechamento.
# ----------------------------------------------------------------------
def parse_ptax(payload: dict, currency: str) -> Iterator[dict]:
    by_day: dict[str, dict] = {}
    for v in payload.get("value", []):
        day = str(v["dataHoraCotacao"])[:10]
        tipo = v.get("tipoBoletim")
        if tipo is not None and tipo != "Fechamento PTAX" and "Fechamento" not in str(tipo):
            # guarda intermediários apenas se não houver fechamento no dia
            by_day.setdefault(day, v)
            continue
        by_day[day] = v
    for day in sorted(by_day):
        v = by_day[day]
        yield {"indicator_code": f"FX_{currency.upper()}_BRL", "geo_iso3": "BRA",
               "period": date.fromisoformat(day), "value": float(v["cotacaoVenda"]),
               "obs_status": "A" if "Fechamento" in str(v.get("tipoBoletim", "Fechamento")) else "P"}


class PtaxJob(Job):
    source_id, dataset = "bcb_ptax", "series"

    def __init__(self, currency: str, start: date, end: date, file: Path | None = None):
        self.currency, self.start, self.end, self.file = currency.upper(), start, end, file
        self.job_name = f"bcb.ptax.{self.currency.lower()}"

    def params(self):
        return {"currency": self.currency, "start": self.start.isoformat(), "end": self.end.isoformat()}

    def fetch(self, ctx):
        if self.file:
            return [ctx.register_raw(f"file://{Path(self.file).resolve()}", Path(self.file), None, {}, f"ptax_{self.currency}.json")]
        base = ctx.settings.ptax_url + ("CotacaoMoedaPeriodo(moeda=@moeda,dataInicial=@dataInicial,"
                                        "dataFinalCotacao=@dataFinalCotacao)")
        q = (f"?@moeda='{self.currency}'&@dataInicial='{self.start:%m-%d-%Y}'"
             f"&@dataFinalCotacao='{self.end:%m-%d-%Y}'&$format=json&$top=100000")
        url = base + quote(q, safe="?&=@$'")
        tmp, st = http_download(url, ctx.settings)
        try:
            return [ctx.register_raw(url, tmp, st, {}, f"ptax_{self.currency}.json")]
        finally:
            tmp.unlink(missing_ok=True)

    def rows(self, ctx, files):
        for f in files:
            yield from parse_ptax(json.loads(Path(f).read_text(encoding="utf-8")), self.currency)


# ----------------------------------------------------------------------
# FRED — dois modos:
#   • API (series/observations, JSON) quando FRED_API_KEY está configurada;
#   • fredgraph.csv (público, sem chave) caso contrário. Mesmo dado, outro formato.
# Valor ausente ('.' na API, vazio no CSV — feriados em séries diárias) → obs_status 'M'.
# ----------------------------------------------------------------------
def parse_fred(payload: dict, indicator_code: str, geo: str) -> Iterator[dict]:
    for o in payload.get("observations", []):
        v = parse_decimal(o.get("value"))
        yield {"indicator_code": indicator_code, "geo_iso3": geo, "period": date.fromisoformat(o["date"]),
               "value": v, "obs_status": "A" if v is not None else "M"}


def parse_fred_csv(text: str, indicator_code: str, geo: str) -> Iterator[dict]:
    rd = csv.reader(text.splitlines())
    header = next(rd, None)
    if not header or header[0].lower() not in ("observation_date", "date"):
        raise ValueError(f"CSV do FRED com cabeçalho inesperado: {header}")
    for row in rd:
        if not row or not row[0].strip():
            continue
        v = parse_decimal(row[1] if len(row) > 1 else None)
        yield {"indicator_code": indicator_code, "geo_iso3": geo, "period": date.fromisoformat(row[0].strip()),
               "value": v, "obs_status": "A" if v is not None else "M"}


class FredJob(Job):
    source_id, dataset = "fred", "series"

    def __init__(self, series_id: str, indicator_code: str, geo: str = "USA", start: date | None = None,
                 file: Path | None = None):
        self.series_id, self.indicator_code, self.geo, self.start, self.file = series_id, indicator_code, geo, start, file
        self.job_name = f"fred.{series_id.lower()}"
        self._mode = "file"

    def params(self):
        return {"series_id": self.series_id, "indicator": self.indicator_code, "geo": self.geo, "mode": self._mode}

    def fetch(self, ctx):
        if self.file:
            return [ctx.register_raw(f"file://{Path(self.file).resolve()}", Path(self.file), None, {}, Path(self.file).name)]
        start = (self.start or date(2000, 1, 1)).isoformat()
        if ctx.settings.fred_api_key:
            self._mode = "api"
            p = {"series_id": self.series_id, "api_key": ctx.settings.fred_api_key, "file_type": "json",
                 "observation_start": start}
            tmp, st = http_download(ctx.settings.fred_url, ctx.settings, params=p)
            name, uri = f"fred_{self.series_id}.json", f"{ctx.settings.fred_url}?series_id={self.series_id}"  # URI sem a chave
        else:
            self._mode = "fredgraph_csv"
            uri = ctx.settings.fredgraph_url.format(series=self.series_id, start=start)
            tmp, st = http_download(uri, ctx.settings)
            name = f"fred_{self.series_id}.csv"
        try:
            return [ctx.register_raw(uri, tmp, st, {"mode": self._mode}, name)]
        finally:
            tmp.unlink(missing_ok=True)

    def rows(self, ctx, files):
        for f in files:
            text = Path(f).read_text(encoding="utf-8-sig")
            if text.lstrip().startswith("{"):
                yield from parse_fred(json.loads(text), self.indicator_code, self.geo)
            else:
                yield from parse_fred_csv(text, self.indicator_code, self.geo)


# ----------------------------------------------------------------------
# IBGE SIDRA — parser genérico da API /values
# A 1ª linha do JSON é o cabeçalho (código → rótulo). Seleção de linhas
# por rótulos de dimensão (ex.: {"Tipo de produto da silvicultura": "Madeira em tora"}).
# ----------------------------------------------------------------------
_PERIOD_LABELS = ("Ano", "Mês", "Trimestre")


def _sidra_period(code: str, label: str) -> date:
    code = str(code)
    if label == "Mês" and len(code) == 6:
        return date(int(code[:4]), int(code[4:]), 1)
    if label == "Trimestre" and len(code) == 6:
        return date(int(code[:4]), (int(code[4:]) - 1) * 3 + 1, 1)
    return date(int(code[:4]), 1, 1)


def parse_sidra(payload: list, indicator_code: str, match: dict[str, str], geo: str = "BRA",
                scale: float = 1.0) -> Iterator[dict]:
    if not payload:
        return
    header, rows = payload[0], payload[1:]
    dims = {k[:-1]: lbl for k, lbl in header.items() if k.startswith("D") and k.endswith("N")}
    period_key = next((k for k, lbl in dims.items() if lbl in _PERIOD_LABELS), None)
    if period_key is None:
        raise ValueError("cabeçalho SIDRA sem dimensão de período")
    label_to_key = {lbl: k for k, lbl in dims.items()}
    for want in match:
        if want not in label_to_key:
            raise ValueError(f"dimensão '{want}' não existe na resposta SIDRA: {sorted(label_to_key)}")
    for r in rows:
        if all(str(r.get(label_to_key[l] + "N", "")).strip().lower() == v.strip().lower() for l, v in match.items()):
            v = parse_decimal(r.get("V"))
            yield {"indicator_code": indicator_code, "geo_iso3": geo,
                   "period": _sidra_period(r[period_key + "C"], dims[period_key]),
                   "value": None if v is None else v * scale, "obs_status": "A" if v is not None else "M"}


class SidraJob(Job):
    source_id, dataset = "ibge_sidra", "series"

    def __init__(self, path: str, indicator_code: str, match: dict[str, str], scale: float = 1.0,
                 file: Path | None = None):
        """path: trecho após /values, ex. '/t/291/n1/all/v/all/p/all/c194/all' (confirmar tabela)."""
        self.path, self.indicator_code, self.match, self.scale, self.file = path, indicator_code, match, scale, file
        self.job_name = f"ibge.sidra.{indicator_code.lower()}"

    def params(self):
        return {"path": self.path, "indicator": self.indicator_code, "match": self.match}

    def fetch(self, ctx):
        if self.file:
            return [ctx.register_raw(f"file://{Path(self.file).resolve()}", Path(self.file), None, {}, "sidra.json")]
        url = ctx.settings.sidra_url + self.path
        tmp, st = http_download(url, ctx.settings)
        try:
            return [ctx.register_raw(url, tmp, st, {}, "sidra.json")]
        finally:
            tmp.unlink(missing_ok=True)

    def rows(self, ctx, files):
        for f in files:
            yield from parse_sidra(json.loads(Path(f).read_text(encoding="utf-8")), self.indicator_code,
                                   self.match, scale=self.scale)


# ----------------------------------------------------------------------
# IBGE PEVS — tabela 291 (silvicultura), variável 142 (m³), classificação 194.
# Categorias confirmadas no serviço de metadados (servicodados.ibge.gov.br/api/v3/agregados/291/metadados).
# Indicadores somam categorias oficiais; se alguma parcela faltar, o total fica ausente ('M'), nunca parcial.
# ----------------------------------------------------------------------
PEVS_PATH = "/t/291/n1/all/v/142/p/all/c194/33253,33254,33256,33257"
PEVS_SPEC: dict[str, tuple[str, ...]] = {
    "BR_SILV_PINUS_M3": ("33254", "33257"),        # tora de pinus: celulose + outras finalidades
    "BR_SILV_EUCA_M3": ("33253", "33256"),         # tora de eucalipto: celulose + outras finalidades
    "BR_SILV_PINUS_OTHER_M3": ("33257",),          # pinus p/ serraria, laminação e outras
    "BR_SILV_EUCA_OTHER_M3": ("33256",),
}


def parse_pevs(payload: list, spec: dict[str, tuple[str, ...]] = PEVS_SPEC, geo: str = "BRA") -> Iterator[dict]:
    if not payload:
        return
    header, rows = payload[0], payload[1:]
    dims = {k[:-1]: lbl for k, lbl in header.items() if k.startswith("D") and k.endswith("N")}
    yk = next(k for k, l in dims.items() if l == "Ano")
    ck = next(k for k, l in dims.items() if l == "Tipo de produto da silvicultura")
    vals: dict[str, dict[str, float | None]] = defaultdict(dict)
    for r in rows:
        vals[str(r[yk + "C"])][str(r[ck + "C"])] = parse_decimal(r.get("V"))
    for year in sorted(vals):
        for ind, cats in spec.items():
            got = [vals[year].get(c) for c in cats]
            if all(c not in vals[year] for c in cats):
                continue
            if all(g is None for g in got) and int(year) < 2013:
                continue  # detalhe por espécie só existe a partir de 2013
            ok = all(g is not None for g in got)
            yield {"indicator_code": ind, "geo_iso3": geo, "period": date(int(year), 1, 1),
                   "value": sum(got) if ok else None, "obs_status": "A" if ok else "M"}


class PevsJob(Job):
    source_id, dataset, job_name = "ibge_sidra", "series", "ibge.sidra.pevs291"

    def __init__(self, file: Path | None = None):
        self.file = file

    def params(self):
        return {"path": PEVS_PATH, "spec": {k: list(v) for k, v in PEVS_SPEC.items()}}

    def fetch(self, ctx):
        if self.file:
            return [ctx.register_raw(f"file://{Path(self.file).resolve()}", Path(self.file), None, {}, "pevs291.json")]
        url = ctx.settings.sidra_url + PEVS_PATH
        tmp, st = http_download(url, ctx.settings)
        try:
            return [ctx.register_raw(url, tmp, st, {"table": 291}, "pevs291.json")]
        finally:
            tmp.unlink(missing_ok=True)

    def rows(self, ctx, files):
        for f in files:
            yield from parse_pevs(json.loads(Path(f).read_text(encoding="utf-8")))


# PIM-PF: tabela 8888, variável 12607 (índice 2022=100 dessazonalizado), CNAE 16 (categoria 129323)
PIM_WOOD = {"path": "/t/8888/n1/all/v/12607/p/all/c544/129323", "indicator": "BR_IP_WOOD",
            "match": {"Seções e atividades industriais (CNAE 2.0)": "3.16 Fabricação de produtos de madeira"}}


# ----------------------------------------------------------------------
# FAOSTAT — arquivo "Forestry_E_All_Data_(Normalized).csv"
# Mapeamento Item|Element → indicador vem de dim_indicator.source_ref.
# ----------------------------------------------------------------------
def parse_faostat(rows: Iterable[dict], mapping: dict[str, str], m49_to_iso3: dict[int, str]) -> Iterator[dict]:
    for r in rows:
        key = f"{r.get('Item', '').strip()}|{r.get('Element', '').strip()}"
        ind = mapping.get(key)
        if not ind:
            continue
        m49_raw = str(r.get("Area Code (M49)", "")).strip().lstrip("'")
        iso3 = m49_to_iso3.get(int(m49_raw)) if m49_raw.isdigit() else None
        if not iso3:
            continue
        v = parse_decimal(r.get("Value"))
        flag = (r.get("Flag") or "").strip()
        yield {"indicator_code": ind, "geo_iso3": iso3, "period": date(int(r["Year"]), 1, 1), "value": v,
               "obs_status": "M" if v is None else ("E" if flag in ("E", "I", "X") else "A")}


class FaostatJob(Job):
    source_id, dataset, job_name = "fao", "series", "fao.forestry"

    def __init__(self, file: Path):
        self.file = Path(file)

    def params(self):
        return {"file": str(self.file)}

    def fetch(self, ctx):
        return [ctx.register_raw(f"file://{self.file.resolve()}", self.file, None, {}, self.file.name)]

    def rows(self, ctx, files):
        mapping = {r["source_ref"]: r["indicator_code"] for r in ctx.db.query(
            "SELECT indicator_code, source_ref FROM dw.dim_indicator WHERE source_id = 'fao' AND source_ref IS NOT NULL")}
        m49 = {int(r["m49"]): r["iso3"] for r in ctx.db.query(
            "SELECT m49, iso3 FROM dw.dim_country WHERE m49 IS NOT NULL")}
        for f in files:
            with open(f, encoding="utf-8-sig", errors="replace", newline="") as fh:
                yield from parse_faostat(csv.DictReader(fh), mapping, m49)


# ----------------------------------------------------------------------
# CSV manual — para fontes licenciadas/sem API (Drewry, ITTO, Ibá, ANFIR…)
# Colunas: indicator_code, geo_iso3, period (AAAA | AAAA-MM | AAAA-MM-DD), value [, obs_status]
# ----------------------------------------------------------------------
def _parse_period(s: str) -> date:
    s = s.strip()
    if len(s) == 4:
        return date(int(s), 1, 1)
    if len(s) == 7:
        return date(int(s[:4]), int(s[5:7]), 1)
    return datetime.strptime(s[:10], "%Y-%m-%d").date()


def parse_manual_csv(path: Path) -> Iterator[dict]:
    text = Path(path).read_text(encoding="utf-8-sig")
    delim = ";" if text.splitlines()[0].count(";") > text.splitlines()[0].count(",") else ","
    for r in csv.DictReader(text.splitlines(), delimiter=delim):
        v = parse_decimal(r.get("value"))
        yield {"indicator_code": r["indicator_code"].strip(), "geo_iso3": r["geo_iso3"].strip().upper(),
               "period": _parse_period(r["period"]), "value": v,
               "obs_status": (r.get("obs_status") or ("M" if v is None else "A")).strip()}


class ManualSeriesJob(Job):
    dataset = "series"

    def __init__(self, file: Path, source_id: str):
        self.file, self.source_id = Path(file), source_id
        self.job_name = f"manual.{source_id}"

    def params(self):
        return {"file": str(self.file)}

    def fetch(self, ctx):
        return [ctx.register_raw(f"file://{self.file.resolve()}", self.file, None, {"mode": "manual"}, self.file.name)]

    def rows(self, ctx, files):
        known = {r["indicator_code"] for r in ctx.db.query("SELECT indicator_code FROM dw.dim_indicator")}
        for f in files:
            for r in parse_manual_csv(f):
                if r["indicator_code"] not in known:
                    r["_reject"] = "indicador não cadastrado em dw.dim_indicator"
                yield r
