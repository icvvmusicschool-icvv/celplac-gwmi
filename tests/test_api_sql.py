"""API: todas as consultas nomeadas + lógica dos endpoints contra PostgreSQL populado.

Sem FastAPI instalado, as funções de endpoint são chamadas diretamente (stub);
com FastAPI, o mesmo arquivo roda igual (as funções continuam chamáveis).
"""
import tempfile
from datetime import date
from pathlib import Path

from common import FIX, fresh_database, get_db

try:
    import fastapi  # noqa: F401
    from psycopg.rows import dict_row  # noqa: F401
    HAVE_STACK = True
except ImportError:
    HAVE_STACK = False
    from support.fastapi_stub import install
    install()

from app.db import Repo, queries  # noqa: E402
from app.routers import analytics, intel, meta, series, trade  # noqa: E402
from gwmi_etl.config import Settings  # noqa: E402
from gwmi_etl.connectors.comexstat import REF_ORDER, ComexTradeJob, run_comex_reference  # noqa: E402
from gwmi_etl.demo import DEMO_DATA, DemoSeriesJob, DemoTradeJob  # noqa: E402
from gwmi_etl.jobs import import_intel, run_derive, run_signals  # noqa: E402
from gwmi_etl.pipeline import run_job  # noqa: E402

DB = REPO = None


def setup_module():
    global DB, REPO
    dsn = fresh_database()
    DB = get_db(dsn)
    s = Settings(database_url=dsn, raw_dir=Path(tempfile.mkdtemp()))
    # 1) só DEMO
    for j in (DemoTradeJob(), DemoSeriesJob()):
        assert run_job(DB, j, s).status == "success"
    import_intel(DB, DEMO_DATA / "events.jsonl", "events", True)
    import_intel(DB, DEMO_DATA / "news.jsonl", "news", True)
    for g in ("br_exports", "market_imports"):
        run_derive(DB, g)
    run_signals(DB, date(2026, 8, 1))
    if HAVE_STACK:
        from app.db import make_pool
        REPO = Repo(make_pool(dsn))
    else:
        from support.fastapi_stub import PsqlPool
        REPO = Repo(PsqlPool(DB))


SAMPLE = {
    "sources_by_ids": {"ids": ["comexstat", "demo"]}, "series_history": {"codes": ["WOOD_PRICE_INDEX"], "since": date(2025, 1, 1)},
    "series_monthly": {"code": "FX_USD_BRL", "geo": "BRA", "from": date(2025, 1, 1), "to": date(2026, 12, 1)},
    "series_native": {"code": "FX_USD_BRL", "geo": "BRA", "from": date(2026, 8, 1), "to": date(2026, 8, 31)},
    "series_latest": {"category": None, "geo": None},
    "exports_summary": {"end": None, "months": 12, "family": None},
    "export_destinations": {"end": None, "months": 12, "family": "plywood"},
    "exports_by_hs6": {"end": None, "months": 12}, "export_flows": {"end": None, "months": 12},
    "trade_monthly": {"family": None, "partner": "USA", "flow": "X"},
    "ncm_search": {"q": "4412", "family": None, "partner": None, "year": 2026, "month": None, "flow": "X"},
    "competitors": {"hs4": "4412", "year": None},
    "correlation_pair": {"x_code": "FX_USD_BRL", "x_geo": "BRA", "y_code": "EXP_BR_VALUE", "y_geo": "WLD", "since": date(2021, 1, 1)},
    "market_cycle": {"threshold": None},
    "events": {"category": None, "country": "USA", "allow_sim": True, "limit": 10},
    "news": {"impact_class": "direto", "allow_sim": True, "limit": 10},
    "alerts_open": {"allow_sim": True}, "index_config": {"config_id": None},
    "index_series": {"codes": ["FX_USD_BRL", "WOOD_PRICE_INDEX"], "geos": ["BRA", "WLD"]},
    "trace_trade": {"id": 1}, "trace_series": {"code": "WOOD_PRICE_INDEX", "geo": "WLD", "period": None},
    "runs_recent": {"limit": 5},
}
WRITES = {"index_config_insert"}


def test_every_named_query_executes():
    for name, sql in queries().items():
        if name in WRITES:
            continue
        rows = DB.query(sql, SAMPLE.get(name, {}))
        assert isinstance(rows, list), name


def test_pulse_envelope_marks_simulated():
    r = series.pulse(history_months=24, repo=REPO)
    assert r["status"] == "ok" and r["meta"]["is_simulated"] is True
    keys = [i["pulse_key"] for i in r["data"]]
    assert keys == ["WOOD", "PLYWOOD", "VENEER", "CONSTRUCTION", "TRUCKING", "SHIPPING", "USD/BRL", "CHINA", "USA", "EUROPE"]
    assert all(len(i["history"]) >= 20 for i in r["data"])
    assert "demo" in {s["source_id"] for s in r["meta"]["sources"]}
    assert r["meta"]["notes"][0].startswith("SIMULATED DATA")


def test_exports_and_shift():
    s = trade.exports_summary(months=12, end=None, family=None, repo=REPO)
    assert s["status"] == "ok" and s["data"]["destinations"] == 24
    d = trade.destinations(months=12, end=None, family=None, repo=REPO)["data"]
    assert d[0]["iso3"] == "USA" and d[0]["trend"] == "↓"
    sh = trade.shift(months=12, end=None, family=None, min_delta=0.002, repo=REPO)["data"]
    assert "MEX" in [x["iso3"] for x in sh["gaining"]] and "USA" in [x["iso3"] for x in sh["losing"]]
    assert {x["iso3"] for x in sh["new_markets"]} >= {"VNM", "MAR"}
    fl = trade.flows(months=12, end=None, repo=REPO)["data"]
    assert fl and {"Paranaguá", "Itajaí"} <= {f["port_name"] for f in fl}


def test_competitors_default_complete_year():
    r = trade.competitors(hs4="4412", year=None, repo=REPO)
    assert r["data"][0]["iso3"] == "CHN"
    assert "BRA" in [x["iso3"] for x in r["data"]]


def test_fx_correlation_and_macro():
    fx = series.fx(repo=REPO)["data"]
    assert {x["indicator_code"] for x in fx} >= {"FX_USD_BRL", "FX_EUR_BRL"} and all(x["vol_12m"] for x in fx)
    c = series.correlation(x="FX_USD_BRL", x_geo="BRA", y="EXP_BR_VALUE", y_geo="WLD", months=60, repo=REPO)
    assert c["meta"]["kind"] == "analysis" and c["data"]["n"] >= 24 and -1 <= c["data"]["r"] <= 1
    assert any("causalidade" in n for n in c["meta"]["notes"])
    m = series.macro(repo=REPO)["data"]
    assert len({x["geo_iso3"] for x in m}) == 8


def test_intel_signals_cycle():
    ev = intel.events(category="TARIFFS", country=None, limit=10, repo=REPO)
    assert ev["data"] and all(e["evidence"] for e in ev["data"])
    nw = intel.news(impact_class="direto", limit=50, repo=REPO)["data"]
    assert len(nw) == 4
    sg = analytics.signals(repo=REPO)
    results = {(x["rule_id"], x["market_iso3"]): x["result"] for x in sg["data"]}
    assert len(results) == 13
    # regras v2 (0019): frete via proxy declarado; o DEMO não tem o proxy → o frete fica "sem dado"
    mp = next(x for x in sg["data"] if (x["rule_id"], x["market_iso3"]) == ("market_pressure", "USA"))
    assert any(d["indicator"] == "FREIGHT_PPI_DEEPSEA_US" for d in mp["detail"])
    assert results[("market_pressure", "USA")] in ("SINAL", "INDICAÇÃO", "EVIDÊNCIA INSUFICIENTE")
    assert set(results.values()) <= {"SINAL", "INDICAÇÃO", "SEM SINAL", "EVIDÊNCIA INSUFICIENTE"}
    cy = analytics.cycle(momentum_threshold=None, repo=REPO)["data"]
    assert {c["phase"] for c in cy} <= {"EXPANSÃO", "PICO", "DESACELERAÇÃO", "CONTRAÇÃO", "RECUPERAÇÃO", "EVIDÊNCIA INSUFICIENTE"}


def test_index_default_and_custom():
    r = analytics.index(analytics.IndexRequest(), repo=REPO)
    assert r["status"] == "ok" and len(r["data"]["components_used"]) == 10 and len(r["data"]["values"]) >= 24
    r2 = analytics.index(analytics.IndexRequest(components=[
        analytics.Component(indicator="FX_USD_BRL", geo="BRA", weight=1),
        analytics.Component(indicator="NAO_EXISTE", geo="WLD", weight=1)]), repo=REPO)
    assert [m["indicator"] for m in r2["data"]["components_missing"]] == ["NAO_EXISTE"]


def test_traceability():
    t = meta.trace_trade(trade_id=1, repo=REPO)
    assert t["meta"]["is_simulated"] is True and t["data"]["versions"][0]["version"] == 1
    s = meta.trace_series(indicator_code="PLYWOOD_FOB_BR", geo="BRA", period=None, repo=REPO)
    assert s["data"]["formula"] and s["data"]["kind"] == "indicator"


def test_real_data_replaces_demo_and_allow_simulated_switch():
    s = Settings(database_url="", raw_dir=Path(tempfile.mkdtemp()))
    run_comex_reference(DB, s, {t: FIX / f"{t}.csv" for t in REF_ORDER})
    run_job(DB, ComexTradeJob("X", 2025, FIX / "EXP_2025_v2.csv"), s)
    run_derive(DB, "br_exports")
    d = trade.destinations(months=3, end=date(2025, 3, 1), family=None, repo=REPO)
    assert d["meta"]["is_simulated"] is False and d["data"][0]["iso3"] == "USA"
    assert [x["source_id"] for x in d["meta"]["sources"]] == ["comexstat"]
    # desligar dado simulado: endpoint só-DEMO passa a responder DADO INDISPONÍVEL
    DB.execute("UPDATE meta.setting SET value = '{\"allow_simulated\": false}' WHERE key = 'api'")
    try:
        c = trade.competitors(hs4="4412", year=None, repo=REPO)
        assert c["status"] == "DADO INDISPONÍVEL" and c["data"] == []
        assert trade.destinations(months=3, end=date(2025, 3, 1), family=None, repo=REPO)["status"] == "ok"
    finally:
        DB.execute("UPDATE meta.setting SET value = '{\"allow_simulated\": true}' WHERE key = 'api'")


def test_sources_and_quality():
    q = meta.quality(repo=REPO)["data"]
    st = {x["source_id"]: x["integration_status"] for x in q["sources"]}
    assert st["comexstat"] == "INTEGRADO" and st["demo"] == "SIMULADO" and st["fred"] == "SEM DADOS"


def test_panel_package_real_only():
    """/v1/panel: o pacote do painel nunca carrega linha simulada."""
    from app import panel
    d = panel.build(REPO)
    assert set(d) >= {"ASOF", "S", "I", "T", "SIG", "DQ", "RUNS", "RAW", "COMPY"}
    blob = __import__("json").dumps(d, default=str)
    assert '"is_simulated": true' not in blob
    assert all(s["v"] for s in d["S"])
    sim = panel.real_only([{"a": 1, "is_simulated": True}, {"a": 2, "is_simulated": False}, {"x": {"is_simulated": True}}])
    assert sim == [{"a": 2, "is_simulated": False}, {"x": None}]


def test_api_key_check():
    import os
    from app import auth

    class Req:
        def __init__(self, method="GET", headers=None):
            self.method, self.headers = method, {k.lower(): v for k, v in (headers or {}).items()}

    good = "k" * 40
    os.environ.pop("GWMI_OPEN_READ", None)
    os.environ["GWMI_API_KEYS"] = ""
    for hdr in ({}, {"X-API-Key": good}):
        try:
            auth.require_key(Req(headers=hdr))
            raise AssertionError("sem chave configurada deveria bloquear")
        except Exception as e:
            assert getattr(e, "status_code", None) == 503
    os.environ["GWMI_API_KEYS"] = "curta," + good          # chave curta é ignorada
    auth.require_key(Req(headers={"X-API-Key": good}))
    auth.require_key(Req(headers={"Authorization": "Bearer " + good}))
    for hdr in ({}, {"X-API-Key": "curta"}, {"X-API-Key": good + "x"}):
        try:
            auth.require_key(Req(headers=hdr))
            raise AssertionError("chave inválida deveria dar 401")
        except Exception as e:
            assert getattr(e, "status_code", None) == 401
    os.environ["GWMI_OPEN_READ"] = "1"
    auth.require_key(Req())                                   # leitura aberta
    try:
        auth.require_key(Req(method="POST"))
        raise AssertionError("escrita sem chave deveria dar 401")
    except Exception as e:
        assert getattr(e, "status_code", None) == 401
    os.environ.pop("GWMI_OPEN_READ"); os.environ.pop("GWMI_API_KEYS")
