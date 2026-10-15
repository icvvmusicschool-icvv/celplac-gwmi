"""Conectores das fontes abertas (Eurostat, DBnomics/NBS, INDEC, IBGE IPP, PEVS preço, FRED a/a) e o plano diário."""
import json
from datetime import date

from common import FIX

from gwmi_etl.connectors import open_sources as o


def _vals(rows):
    return {(r["period"].isoformat()[:7], r["indicator_code"], r["geo_iso3"]): r["value"] for r in rows}


def test_eurostat_jsonstat_with_gaps():
    rows = list(o.parse_eurostat(json.loads((FIX / "eurostat_sts_inpr_m.json").read_text()), "MACRO_IP_YOY", "EUU"))
    v = _vals(rows)
    assert v[("2026-04", "MACRO_IP_YOY", "EUU")] == 1.2
    assert v[("2026-06", "MACRO_IP_YOY", "EUU")] is None          # sem valor → ausente, nunca zero
    assert [r["obs_status"] for r in rows] == ["A", "A", "M", "A"]


def test_dbnomics_nbs_na_and_start():
    rows = list(o.parse_dbnomics(json.loads((FIX / "dbnomics_nbs.json").read_text()), "MACRO_IP_YOY", "CHN"))
    assert [r["period"].isoformat()[:7] for r in rows] == ["2025-11", "2025-12", "2026-01", "2026-02"]  # 2020 fora
    assert rows[1]["value"] == 5.2 and rows[2]["value"] is None and rows[2]["obs_status"] == "M"


def test_datos_ar_percent_times_100():
    rows = list(o.parse_datos_ar(json.loads((FIX / "datos_ar_ipi.json").read_text()), "MACRO_IP_YOY"))
    assert rows[0]["value"] == -3.12 and rows[1]["value"] is None and rows[2]["value"] == -4.877


def test_sidra_single_ipp():
    rows = list(o.parse_sidra_single(json.loads((FIX / "sidra_ipp6903.json").read_text()), "BR_IPP_WOOD"))
    assert rows[0]["period"] == date(2026, 6, 1) and rows[0]["value"] == 161.53
    assert rows[1]["value"] is None


def test_pevs_implicit_price():
    rows = list(o.parse_pevs_price(json.loads((FIX / "sidra_pevs_preco.json").read_text())))
    v = {r["period"].year: r["value"] for r in rows}
    assert 2012 not in v                        # antes de 2013 fica de fora
    assert v[2025] == 164.77                    # o mesmo valor carregado pela coleta do navegador
    assert v[2024] is None                      # quantidade ausente → preço ausente


def test_fred_yoy():
    rows = list(o.parse_fred_yoy((FIX / "fred_indpro.csv").read_text(), "MACRO_IP_YOY", "USA", start="2026-01"))
    v = {r["period"].isoformat()[:7]: r["value"] for r in rows}
    assert v == {"2026-06": 1.5, "2026-07": -0.5, "2026-08": None}   # base ausente → a/a ausente


def test_daily_plan_gates():
    from gwmi_etl.update import plan
    tue = [s.label for s in plan(date(2026, 10, 6))]
    mon = [s.label for s in plan(date(2026, 10, 5))]          # 1ª segunda-feira do mês
    assert any(l.startswith("Comex Stat exportações 2026") for l in tue)
    assert not any("Comtrade" in l or "PEVS" in l for l in tue)
    assert sum("Comtrade importações" in l for l in mon) == 14
    assert sum("Comtrade concorrentes" in l for l in mon) == 6
    assert any("PEVS" in l for l in mon)
    feb = [s.label for s in plan(date(2027, 2, 9))]
    assert "Comex Stat exportações 2026" in feb and "Comex Stat exportações 2027" in feb
