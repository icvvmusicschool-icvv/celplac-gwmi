"""Gerador DEMO — dados SIMULADOS, determinísticos (seed fixa).

Tudo que sai daqui entra com source_id='demo' e is_simulated=true.
Quando o dado real de um recorte é carregado, as views mart.* passam a
ignorar automaticamente o simulado daquele recorte.
"""
from __future__ import annotations

import json
import math
import random
from datetime import date, timedelta
from pathlib import Path
from typing import Iterator

from .pipeline import Job

SEED = 20260923
END = date(2026, 8, 1)
N_MONTHS = 60


def months_back(n: int, end: date = END) -> list[date]:
    out, y, m = [], end.year, end.month
    for _ in range(n):
        out.append(date(y, m, 1))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out[::-1]


# Exportações BR — US$ milhões nos 12m atuais vs 12m anteriores (narrativa do protótipo)
PARTNERS = {
    "USA": (182, 214), "MEX": (64, 49), "DEU": (38, 33), "BEL": (31, 27), "GBR": (29, 28), "NLD": (22, 19),
    "ARG": (21, 24), "DOM": (18, 15), "SAU": (16, 11), "FRA": (15, 14), "CHL": (14, 15), "PRY": (12, 11),
    "URY": (11, 11), "CHN": (10, 17), "PER": (9, 8), "IND": (8, 5), "COL": (7, 6), "ESP": (7, 7),
    "CAN": (6, 5), "POL": (6, 4), "ITA": (5, 6), "MAR": (5, 1.2), "VNM": (4, 0.6), "ZAF": (4, 4),
}
NCM_SPLIT = [("44123900", .52, 520), ("44123400", .14, 600), ("44123100", .06, 600),
             ("44081000", .07, 550), ("44124900", .05, 520), ("44071100", .16, 500)]
UF_URF = [("PR", 990001, .48), ("SC", 990002, .38), ("RS", 990004, .09), ("SP", 990005, .05)]
DEMO_URF = [(990001, "DEMO — Paranaguá", "BRPNG"), (990002, "DEMO — Itajaí/Itapoá", "BRITJ"),
            (990003, "DEMO — São Francisco do Sul", "BRSFS"), (990004, "DEMO — Rio Grande", "BRRIG"),
            (990005, "DEMO — Santos", "BRSSZ")]

COMPETITORS = {  # exportações mundiais de compensado, US$ bi (ano atual, ano anterior)
    "CHN": (7.8, 7.56), "IDN": (1.9, 1.94), "VNM": (1.1, 1.01), "RUS": (.95, 1.08), "MYS": (.88, .91),
    "FIN": (.8, .79), "CHL": (.52, .51), "CAN": (.41, .42), "USA": (.39, .39), "URY": (.12, .11), "PRY": (.08, .076),
}
MARKET_IMPORTS = {  # importações SH4412 do mercado (US$ mi/mês), variação anual recente
    "USA": (430, -.06), "MEX": (38, .08), "CHN": (95, -.03), "ARG": (9, -.05), "SAU": (31, .07),
    "DEU": (60, .03), "BEL": (28, .04), "GBR": (70, .01), "NLD": (41, .04), "FRA": (37, .02),
}


def _walk(rng: random.Random, n: int, start: float, drift: float, vol: float, seas: float = 0.0,
          last_change: float | None = None) -> list[float]:
    v, out = start, []
    for i in range(n):
        v *= 1 + drift + (rng.random() - .5) * vol
        out.append(v * (1 + seas * math.sin(i / 12 * 2 * math.pi)))
    if last_change is not None and n > 1:
        out[-1] = out[-2] * (1 + last_change)
    return out


class DemoTradeJob(Job):
    source_id, dataset, job_name, is_simulated = "demo", "trade", "demo.trade", True

    def rows(self, ctx, files) -> Iterator[dict]:
        ctx.db.execute(
            """INSERT INTO dw.map_urf_port (co_urf, urf_name, port_code, run_id)
               SELECT u.c, u.n, u.p, %(r)s FROM (VALUES """ +
            ", ".join(f"({c}, '{n}', '{p}')" for c, n, p in DEMO_URF) +
            """) AS u(c, n, p) ON CONFLICT (co_urf) DO NOTHING""", {"r": ctx.run_id})
        rng = random.Random(SEED)
        months = months_back(N_MONTHS)
        for iso3, (v, v0) in PARTNERS.items():
            g = (v / v0) ** (1 / 12)                       # crescimento mensal implícito
            price = 330 + rng.random() * 190
            for i, p in enumerate(months):
                back = N_MONTHS - 1 - i
                base = v / 12 * g ** (-back) if back < 24 else v0 / 12 * (1 + .01 * (back - 23)) ** -1
                mval = base * (1 + .06 * math.sin(i / 12 * 2 * math.pi)) * (1 + (rng.random() - .5) * .16)
                ufs = UF_URF if iso3 not in ("ARG", "PRY", "URY") else [("RS", 990004, .6), ("PR", 990001, .4)]
                for ncm, share, dens in NCM_SPLIT:
                    for uf, urf, us in ufs[:2] if share < .1 else ufs:
                        val = mval * 1e6 * share * us / (sum(x[2] for x in (ufs[:2] if share < .1 else ufs)))
                        pr = price * (1.35 if ncm.startswith("4408") else 1.0) * (1 + (rng.random() - .5) * .06)
                        m3 = val / pr
                        yield {"flow": "X", "period": p, "reporter_code": "BRA", "partner_code": iso3,
                               "code_scheme": "iso3", "ncm8": ncm, "uf": uf, "urf_code": urf, "via_code": 1,
                               "value_usd_fob": round(val, 2), "net_kg": round(m3 * dens, 3),
                               "qty_stat": None, "stat_unit_code": None}
        # concorrentes (exportações mundiais por país, parceiro = mundo)
        for iso3, (v, v0) in COMPETITORS.items():
            for p in months_back(36):
                annual = v if p > date(END.year - 1, END.month, 1) else v0
                val = annual * 1e9 / 12 * (1 + (rng.random() - .5) * .1)
                yield {"flow": "X", "period": p, "reporter_code": iso3, "partner_code": "WLD", "code_scheme": "iso3",
                       "ncm8": "44123900", "value_usd_fob": round(val, 2), "net_kg": round(val / 420 * 520, 3)}
        # importações dos mercados (todas as origens)
        for iso3, (lvl, yoy) in MARKET_IMPORTS.items():
            g = (1 + yoy) ** (1 / 12)
            for i, p in enumerate(months):
                back = N_MONTHS - 1 - i
                val = lvl * 1e6 * g ** (-back) * (1 + .05 * math.sin(i / 12 * 2 * math.pi)) * (1 + (rng.random() - .5) * .08)
                yield {"flow": "M", "period": p, "reporter_code": iso3, "partner_code": "WLD", "code_scheme": "iso3",
                       "ncm8": "44123900", "value_usd_fob": round(val, 2), "net_kg": round(val / 450 * 520, 3)}


# (indicador, geo, início, drift mensal, vol, sazonalidade, última variação forçada)
SERIES_SPEC = [
    ("WOOD_PRICE_INDEX", "WLD", 100, .0015, .03, .01, .021),
    ("VENEER_PRICE_INDEX", "WLD", 100, .001, .025, 0, .002),
    ("CONSTRUCTION_COMPOSITE", "WLD", 100, .0012, .02, .02, .012),
    ("BR_TRAILERS_REG", "BRA", 9800, .003, .08, .05, -.034),
    ("FREIGHT_CONTAINER_INDEX", "WLD", 1600, .004, .09, 0, -.041),
    ("CN_WOOD_IMPORTS", "CHN", 1.6, .001, .06, .04, .001),
    ("US_HOUSING_STARTS", "USA", 1180, .002, .05, 0, -.027),
    ("EU_PLYWOOD_IMPORTS", "EUU", 620, .0015, .05, .03, .018),
    ("FREIGHT_BR_USEC", "BRA", 2600, -.001, .08, 0, None),
    ("FREIGHT_BR_NEUR", "BRA", 2300, -.001, .08, 0, None),
    ("FREIGHT_BR_ASIA", "BRA", 3100, -.002, .1, 0, None),
    ("BRENT", "WLD", 62, .001, .07, 0, .02),
    ("PRICE_LOG_PINUS", "BRA", 95, .006, .02, 0, .041),
    ("PRICE_RESIN_PHENOLIC", "BRA", 7.5, .005, .02, 0, .021),
    ("BR_IP_WOOD", "BRA", 100, .001, .03, .03, None),
]
FX_SPEC = [("USD", 5.05, .0012, .035, .013), ("EUR", 5.5, .0012, .035, None), ("GBP", 6.3, .001, .035, None),
           ("CNY", .70, .001, .03, None), ("MXN", .27, .001, .04, None)]
MACRO = {  # geo: juros, inflação, PIB, prod.ind., desemprego, construção, confiança
    "BRA": (14.25, 5.1, 2.1, 1.4, 6.2, 2.8, 93), "USA": (4.25, 2.8, 1.8, .9, 4.3, -2.4, 96),
    "CHN": (3.0, .4, 4.6, 5.2, 5.1, -5.8, 89), "EUU": (2.0, 2.1, 1.1, .6, 6.2, 1.9, 97),
    "MEX": (8.0, 3.9, 1.0, .4, 2.7, 3.6, 99), "ARG": (35, 38, 4.2, 3.1, 7.4, 5.9, 91),
    "CHL": (4.75, 4.1, 2.4, 1.8, 8.6, 2.2, 94), "SAU": (5.5, 2.0, 3.1, 2.5, 3.5, 4.1, 101),
}
MACRO_CODES = ["MACRO_POLICY_RATE", "MACRO_CPI_YOY", "MACRO_GDP_YOY", "MACRO_IP_YOY", "MACRO_UNEMP",
               "MACRO_CONSTRUCTION_YOY", "MACRO_CONFIDENCE"]


class DemoSeriesJob(Job):
    source_id, dataset, job_name, is_simulated = "demo", "series", "demo.series", True

    def rows(self, ctx, files) -> Iterator[dict]:
        rng = random.Random(SEED + 1)
        months = months_back(120)
        for ind, geo, start, drift, vol, seas, lastc in SERIES_SPEC:
            for p, v in zip(months, _walk(rng, 120, start, drift, vol, seas, lastc)):
                yield {"indicator_code": ind, "geo_iso3": geo, "period": p, "value": round(v, 4)}
        # câmbio diário (dias úteis, 5 anos)
        d0 = date(END.year - 5, END.month, 1)
        days = []
        d = d0
        while d <= date(2026, 8, 31):
            if d.weekday() < 5:
                days.append(d)
            d += timedelta(days=1)
        for cur, start, drift, vol, lastc in FX_SPEC:
            v = start
            for d in days:
                v *= 1 + drift / 21 + (rng.random() - .5) * vol / 4.6
                yield {"indicator_code": f"FX_{cur}_BRL", "geo_iso3": "BRA", "period": d, "value": round(v, 4)}
        # macro mensal (PIB trimestral) — 60 meses, último valor = narrativa do protótipo
        for geo, vals in MACRO.items():
            for code, target in zip(MACRO_CODES, vals):
                qtr = code == "MACRO_GDP_YOY"
                pts = [p for p in months[-60:] if not qtr or p.month in (1, 4, 7, 10)]
                for k, p in enumerate(pts):
                    back = len(pts) - 1 - k
                    v = target + (rng.random() - .5) * abs(target) * .2 * min(back, 12) / 12 + math.sin(back / 7) * abs(target) * .05
                    if back == 0:
                        v = target
                    yield {"indicator_code": code, "geo_iso3": geo, "period": p, "value": round(v, 3)}
        # anuais: silvicultura BR e FAO (10 anos)
        for ind, geo, start, g in [("BR_SILV_PINUS_M3", "BRA", 41e6, .018), ("BR_SILV_EUCA_M3", "BRA", 140e6, .026),
                                   ("FAO_PLYWOOD_PROD", "CHN", 105e6, .012), ("FAO_PLYWOOD_PROD", "BRA", 2.6e6, .019),
                                   ("FAO_PLYWOOD_PROD", "IDN", 4.4e6, -.008), ("FAO_PLYWOOD_PROD", "USA", 8.6e6, -.003),
                                   ("FAO_PLYWOOD_EXP", "CHN", 10.5e6, .01), ("FAO_PLYWOOD_EXP", "BRA", 1.8e6, .02),
                                   ("FAO_VENEER_PROD", "CHN", 4.6e6, .011), ("FAO_VENEER_PROD", "BRA", .9e6, .014),
                                   ("FAO_PANELS_PROD", "WLD", 380e6, .009)]:
            v = start
            for y in range(2016, 2026):
                v *= 1 + g + (rng.random() - .5) * .03
                yield {"indicator_code": ind, "geo_iso3": geo, "period": date(y, 1, 1), "value": round(v, 0)}


DEMO_DATA = Path(__file__).parent / "demo_data"
