"""Pipeline ponta a ponta em PostgreSQL real: raw → staging → validação → merge
versionado → DQ → derivados → modo DEMO×real → sinais.

Requer servidor PostgreSQL (GWMI_TEST_ADMIN_DSN). Os testes são sequenciais
e compartilham o mesmo banco (recriado em setup_module).
"""
import tempfile
from datetime import date
from pathlib import Path

from common import FIX, fresh_database, get_db
from gwmi_etl.config import Settings
from gwmi_etl.connectors.comexstat import REF_ORDER, ComexTradeJob, run_comex_reference
from gwmi_etl.connectors import comtrade as comtrade_mod
from gwmi_etl.connectors.comtrade import ComtradeJob, ComtradePreviewJob
from gwmi_etl.connectors.series_sources import FredJob, ManualSeriesJob, PevsJob, PtaxJob, SidraJob
from gwmi_etl.demo import DEMO_DATA, DemoSeriesJob, DemoTradeJob
from gwmi_etl.jobs import import_intel, run_derive, run_signals
from gwmi_etl.pipeline import run_job

DB = None
S = None


def setup_module():
    global DB, S
    dsn = fresh_database()
    DB = get_db(dsn)
    S = Settings(database_url=dsn, raw_dir=Path(tempfile.mkdtemp(prefix="gwmi_raw_")))


def one(sql, **p):
    return DB.scalar(sql, p)


def test_01_reference_tables():
    res = {r["kind"]: r for r in run_comex_reference(DB, S, {t: FIX / f"{t}.csv" for t in REF_ORDER})}
    assert res["pais"]["upserted"] == 5 and res["pais"]["unmapped"] == 1        # 905 → sem ISO3 válido
    assert one("SELECT count(*) FROM dw.dim_ncm") == 3                          # só cap. 44
    assert one("SELECT is_m3 FROM dw.dim_stat_unit WHERE co_unid = 11") is True
    assert one("SELECT port_code FROM dw.map_urf_port WHERE co_urf = 1001") == "BRPNG"


def test_02_comex_load_with_rejection_and_lineage():
    rep = run_job(DB, ComexTradeJob("X", 2025, FIX / "EXP_2025_v1.csv"), S)
    assert rep.status == "partial", rep.summary()              # 1 linha rejeitada
    assert (rep.staged, rep.rejected, rep.inserted) == (7, 1, 7)
    assert one("SELECT reason FROM dq.rejected_row WHERE run_id = %(r)s AND dataset = 'trade' LIMIT 1", r=rep.run_id) == "valor FOB negativo"
    assert one("SELECT count(*) FROM dw.fact_trade WHERE partner_iso3 = 'XXX'") == 1
    assert one("SELECT count(*) FROM dw.fact_trade WHERE qty_m3_method = 'stat_unit'") == 7
    ing = DB.query("SELECT content_sha256, bytes FROM raw.ingestion WHERE run_id = %(r)s", {"r": rep.run_id})
    assert len(ing) == 1 and len(ing[0]["content_sha256"]) == 64


def test_03_idempotent_reload():
    rep = run_job(DB, ComexTradeJob("X", 2025, FIX / "EXP_2025_v1.csv"), S)
    assert (rep.inserted, rep.revised, rep.unchanged) == (0, 0, 7)


def test_04_revision_creates_new_version():
    rep = run_job(DB, ComexTradeJob("X", 2025, FIX / "EXP_2025_v2.csv"), S)
    assert rep.status == "success", rep.summary()
    assert (rep.inserted, rep.revised, rep.unchanged) == (1, 1, 6)
    hist = DB.query("""SELECT version, is_current, value_usd_fob FROM dw.fact_trade
                       WHERE partner_iso3 = 'USA' AND period = '2025-01-01' ORDER BY version""")
    assert [(h["version"], h["is_current"], float(h["value_usd_fob"])) for h in hist] == [(1, False, 380000.0), (2, True, 395000.0)]
    # auditoria: o valor antes da revisão continua consultável
    before = one("""SELECT value_usd_fob FROM dw.trade_as_of(
                      (SELECT finished_at FROM meta.etl_run WHERE job = 'comexstat.exp' ORDER BY run_id LIMIT 1))
                    WHERE partner_iso3 = 'USA' AND period = '2025-01-01'""")
    assert float(before) == 380000.0


def test_04b_snapshot_retires_rows_missing_from_new_file():
    # v1 não traz a linha de mar/2025 EUA (era negativa e foi rejeitada) → ao recarregar v1, ela é aposentada
    rep = run_job(DB, ComexTradeJob("X", 2025, FIX / "EXP_2025_v1.csv"), S)
    assert rep.retired == 1, rep.summary()
    assert one("SELECT count(*) FROM dw.fact_trade WHERE is_current AND partner_iso3='USA' AND period='2025-03-01'") == 0
    rep = run_job(DB, ComexTradeJob("X", 2025, FIX / "EXP_2025_v2.csv"), S)   # volta ao estado v2
    assert rep.retired == 0 and rep.inserted == 1


def test_05_marts_on_real_data():
    d = DB.query("SELECT * FROM mart.export_destinations('2025-03-01', 3)")
    assert [x["iso3"] for x in d][:2] == ["USA", "MEX"] and not any(x["is_simulated"] for x in d)
    s = DB.query("SELECT * FROM mart.exports_summary('2025-03-01', 3)")[0]
    assert float(s["value_usd"]) == 395000 + 150000 + 80000 + 342000 + 76000 + 19000 + 190000 + 300000
    assert s["is_simulated"] is False and s["sources"] == ["comexstat"]
    flows = DB.query("SELECT * FROM mart.export_flows('2025-03-01', 3)")
    assert {f["port_name"] for f in flows} >= {"Paranaguá", "Itajaí", "Rio Grande"}


def test_06_series_sources():
    r1 = run_job(DB, PtaxJob("USD", date(2025, 1, 1), date(2025, 1, 31), FIX / "ptax_usd.json"), S)
    assert r1.inserted == 2
    r2 = run_job(DB, FredJob("HOUST", "US_HOUSING_STARTS", "USA", file=FIX / "fred_houst.json"), S)
    assert r2.inserted == 3 and one("SELECT obs_status FROM dw.fact_series WHERE indicator_code='US_HOUSING_STARTS' AND period='2025-02-01'") == "M"
    r3 = run_job(DB, SidraJob("/fixture", "BR_SILV_PINUS_M3", {"Tipo de produto da silvicultura": "Madeira em tora de pinus"},
                              file=FIX / "sidra_silv.json"), S)
    assert r3.inserted == 3
    r4 = run_job(DB, ManualSeriesJob(FIX / "manual_freight.csv", "drewry"), S)
    assert (r4.inserted, r4.rejected) == (3, 1) and r4.status == "partial"


def test_07_comtrade_and_derived():
    rep = run_job(DB, ComtradeJob("842", "202501", file=FIX / "comtrade_usa.json"), S)
    assert rep.inserted == 2
    d1 = run_derive(DB, "market_imports")
    assert d1["is_simulated"] is False
    assert float(one("SELECT value FROM dw.fact_series WHERE indicator_code='IMP_TOTAL_WOOD' AND geo_iso3='USA'")) == 395000000
    d2 = run_derive(DB, "br_exports")
    assert d2["is_simulated"] is False
    v = one("SELECT value FROM dw.fact_series WHERE indicator_code='PLYWOOD_FOB_BR' AND period='2025-01-01' AND is_current")
    assert abs(float(v) - (395000 + 150000) / 1400) < 1e-3


def test_08_data_quality():
    res = {r["rule_id"]: r for r in DB.query("SELECT * FROM dq.run_checks()")}
    assert res["trade.non_negative"]["passed"] is True
    assert res["trade.unmapped_country"]["passed"] is False            # 905 → XXX sinalizado
    assert res["intel.event_evidence"]["passed"] is True
    q = {r["source_id"]: r for r in DB.query("SELECT * FROM dq.v_source_quality")}
    assert q["comexstat"]["integration_status"] == "INTEGRADO"


def test_09_demo_coexists_but_never_overrides_real():
    for job in (DemoTradeJob(), DemoSeriesJob()):
        rep = run_job(DB, job, S)
        assert rep.status == "success", rep.summary()
    assert import_intel(DB, DEMO_DATA / "events.jsonl", "events", True)["imported"] == 11
    assert import_intel(DB, DEMO_DATA / "news.jsonl", "news", True)["imported"] == 12
    # BR exportações: existe dado real → o demo é ignorado
    assert one("SELECT bool_or(is_simulated) FROM mart.v_trade_effective WHERE reporter_iso3 = 'BRA' AND flow = 'X'") is False
    # concorrentes (outros reporters) só existem em DEMO → servidos como simulados
    comp = DB.query("SELECT * FROM mart.competitors('4412')")
    assert comp[0]["iso3"] == "CHN" and comp[0]["is_simulated"] is True
    # FX USD: há 2 dias reais → série efetiva é a real; EUR só DEMO
    fx = {r["indicator_code"]: r for r in DB.query("SELECT * FROM mart.v_series_latest WHERE category = 'fx'")}
    assert fx["FX_USD_BRL"]["is_simulated"] is False and fx["FX_EUR_BRL"]["is_simulated"] is True


def test_10_signals_and_cycle():
    res = run_signals(DB, date(2026, 8, 1))
    assert len(res) == 13
    assert all(r["result"] in ("SINAL", "INDICAÇÃO", "SEM SINAL", "EVIDÊNCIA INSUFICIENTE") for r in res)
    cyc = DB.query("SELECT * FROM mart.market_cycle()")
    assert len(cyc) >= 6 and all(c["phase"] for c in cyc)


def test_11_phase3_sources_fx_cross_pevs_comtrade_preview():
    # FRED CSV (sem chave) + PTAX → taxa cruzada MXN/BRL como INDICADOR calculado
    r = run_job(DB, FredJob("DEXMXUS", "FX_USD_MXN", "MEX", file=FIX / "fred_dexmxus.csv"), S)
    assert (r.inserted, r.status) == (3, "success")
    d = run_derive(DB, "fx_cross")
    assert d["is_simulated"] is False and d["staged"] == 2          # 02 e 03/jan: há PTAX e H.10 no mesmo dia
    v = one("SELECT value FROM dw.fact_series WHERE indicator_code='FX_MXN_BRL' AND period='2025-01-02' AND NOT is_simulated")
    assert abs(float(v) - round(5.4310 / 20.625, 6)) < 1e-9
    assert one("SELECT kind FROM dw.dim_indicator WHERE indicator_code='FX_MXN_BRL'") == "indicator"
    # PEVS: soma de categorias; parcela ausente → total ausente
    r = run_job(DB, PevsJob(FIX / "pevs291.json"), S)
    assert r.status == "success"
    assert float(one("SELECT value FROM dw.fact_series WHERE indicator_code='BR_SILV_PINUS_M3' AND period='2024-01-01' AND is_current AND NOT is_simulated")) == 47595540
    assert one("SELECT value FROM dw.fact_series WHERE indicator_code='BR_SILV_EUCA_M3' AND period='2024-01-01' AND is_current AND NOT is_simulated") is None
    # Comtrade preview: M49 → ISO3 pelo Reporters.json (aqui injetado); país fora da dimensão é rejeitado
    comtrade_mod._REPORTERS_CACHE = {156: "CHN", 842: "USA", 76: "BRA", 490: "S19"}
    r = run_job(DB, ComtradePreviewJob("4412", "X", "2024", "A", file=FIX / "comtrade_preview_x_2024.json"), S)
    assert (r.inserted, r.rejected) == (2, 1)
    assert one("SELECT product_code FROM dw.map_hs6_product WHERE hs6 = '441200'") == "HS4_4412_TOTAL"
    assert one("SELECT qty_m3 FROM dw.fact_trade WHERE source_id='comtrade' AND reporter_iso3='CHN' AND period='2024-01-01'") is None


def test_12_dq_rules_after_phase3():
    res = {r["rule_id"]: r for r in DB.query("SELECT * FROM dq.run_checks(NULL, 'series')")}
    # séries derivadas por parceiro: mês sem embarque não é lacuna
    gaps = DB.query("""SELECT count(*) AS n FROM dw.fact_series s WHERE s.source_id = 'gwmi_calc'
                       AND s.geo_iso3 NOT IN ('WLD','EUU','BRA')""")[0]["n"]
    assert gaps >= 0 and "series.month_gaps" in res
    assert one("SELECT expected_lag_days FROM dw.dim_indicator WHERE indicator_code='BR_SILV_PINUS_M3'") == 640


def test_13_load_series_compact():
    r = DB.query("""SELECT * FROM stg.load_series_compact('fred', 'fred.test', '{}'::jsonb, 'https://x', repeat('a', 64), 10,
                    'BRENT', 'WLD', '2026-09-01=100.5;2026-09-02=;2026-09-03=101')""")[0]
    assert (r["staged"], r["inserted"]) == (3, 3)
    assert one("SELECT obs_status FROM dw.fact_series WHERE indicator_code='BRENT' AND period='2026-09-02' AND NOT is_simulated") == "M"
    assert one("SELECT count(*) FROM raw.ingestion WHERE run_id = %(r)s", r=r["run_id"]) == 1
