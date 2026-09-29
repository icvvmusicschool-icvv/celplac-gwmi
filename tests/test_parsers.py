"""Parsers e validação — funções puras, sem banco."""
import json
from datetime import date

from common import FIX
from gwmi_etl.connectors.comexstat import parse_comex_trade, parse_ref_table
from gwmi_etl.connectors.comtrade import parse_comtrade, parse_comtrade_preview
from gwmi_etl.connectors.series_sources import (parse_fred, parse_fred_csv, parse_manual_csv, parse_pevs, parse_ptax,
                                                parse_sidra)
from gwmi_etl.pipeline import parse_decimal
from gwmi_etl.validation import validate_series_row, validate_trade_row

HS4 = ("4403", "4407", "4408", "4410", "4411", "4412")


def test_parse_decimal():
    assert parse_decimal("1.234,56") == 1234.56
    assert parse_decimal("2380,5") == 2380.5
    assert parse_decimal("1320.5") == 1320.5
    for missing in ("", "-", "..", "...", "X", ".", None):
        assert parse_decimal(missing) is None


def test_comex_filters_chapter_44_and_maps_columns():
    rows = list(parse_comex_trade(FIX / "EXP_2025_v1.csv", "X", HS4))
    assert len(rows) == 8                                   # 9 linhas − 1 fora do cap. 44
    r = rows[0]
    assert r["period"] == date(2025, 1, 1) and r["ncm8"] == "44123900"
    assert r["partner_code"] == "901" and r["code_scheme"] == "comex"
    assert r["urf_code"] == 1001 and r["uf"] == "PR" and r["stat_unit_code"] == 11
    assert r["value_usd_fob"] == 380000 and r["qty_stat"] == 1000


def test_trade_validation_rejects_negative():
    rows = list(parse_comex_trade(FIX / "EXP_2025_v1.csv", "X", HS4))
    reasons = [validate_trade_row(r) for r in rows]
    assert reasons.count(None) == 7
    assert "valor FOB negativo" in reasons


def test_ref_tables():
    pais = list(parse_ref_table(FIX / "PAIS.csv", "PAIS"))
    assert pais[0] == ("pais", "901", "USA", "Estados Unidos", None)
    ncm = list(parse_ref_table(FIX / "NCM.csv", "NCM"))
    assert ncm[0][:3] == ("ncm", "44123900", "11")


def test_ptax_keeps_closing_bulletin():
    rows = list(parse_ptax(json.loads((FIX / "ptax_usd.json").read_text()), "USD"))
    assert [(r["period"], r["value"]) for r in rows] == [(date(2025, 1, 2), 5.431), (date(2025, 1, 3), 5.381)]
    assert all(r["indicator_code"] == "FX_USD_BRL" and r["obs_status"] == "A" for r in rows)


def test_fred_missing_value_is_declared_missing():
    rows = list(parse_fred(json.loads((FIX / "fred_houst.json").read_text()), "US_HOUSING_STARTS", "USA"))
    assert rows[1]["value"] is None and rows[1]["obs_status"] == "M"
    assert validate_series_row(rows[1]) is None               # ausência declarada é válida


def test_sidra_generic_parser():
    rows = list(parse_sidra(json.loads((FIX / "sidra_silv.json").read_text()), "BR_SILV_PINUS_M3",
                            {"Tipo de produto da silvicultura": "Madeira em tora de pinus"}))
    assert len(rows) == 3
    by = {r["period"].year: r for r in rows}
    assert by[2024]["value"] == 46100000 and by[2022]["obs_status"] == "M"


def test_comtrade_parser_maps_world_and_skips_reexports():
    rows = list(parse_comtrade(json.loads((FIX / "comtrade_usa.json").read_text())))
    assert len(rows) == 2
    assert rows[0]["partner_code"] == "WLD" and rows[0]["ncm8"] == "44120000"
    assert rows[0]["value_usd_fob"] == 395000000              # usa FOB quando reportado


def test_manual_csv():
    rows = list(parse_manual_csv(FIX / "manual_freight.csv"))
    assert rows[1]["value"] == 2380.5 and rows[1]["period"] == date(2025, 2, 1)
    assert rows[2]["value"] is None and rows[2]["obs_status"] == "M"


def test_fred_csv_blank_is_missing_not_zero():
    rows = list(parse_fred_csv((FIX / "fred_dexmxus.csv").read_text(), "FX_USD_MXN", "MEX"))
    assert [r["value"] for r in rows] == [20.625, 20.649, None]
    assert rows[-1]["obs_status"] == "M" and rows[0]["period"] == date(2025, 1, 2)


def test_pevs_sums_official_categories_and_never_partial():
    rows = {(r["indicator_code"], r["period"].year): r for r in parse_pevs(json.loads((FIX / "pevs291.json").read_text()))}
    assert rows[("BR_SILV_PINUS_M3", 2024)]["value"] == 16276790 + 31318750
    assert rows[("BR_SILV_PINUS_OTHER_M3", 2024)]["value"] == 31318750
    # eucalipto: uma das parcelas veio "..." → total ausente, não parcial
    assert rows[("BR_SILV_EUCA_M3", 2024)]["value"] is None and rows[("BR_SILV_EUCA_M3", 2024)]["obs_status"] == "M"
    assert ("BR_SILV_PINUS_M3", 2012) not in rows          # sem detalhe por espécie antes de 2013


def test_comtrade_preview_maps_m49_and_excludes_brazil():
    payload = json.loads((FIX / "comtrade_preview_x_2024.json").read_text())
    rows = list(parse_comtrade_preview(payload, {156: "CHN", 842: "USA", 76: "BRA", 490: "S19"}))
    assert [r["reporter_code"] for r in rows] == ["CHN", "USA", "S19"]      # BRA vem do Comex; RX fora
    assert rows[0]["ncm8"] == "44120000" and rows[0]["partner_code"] == "WLD" and rows[0]["period"] == date(2024, 1, 1)
    assert rows[1]["net_kg"] is None
