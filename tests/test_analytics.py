"""Núcleo analítico (gwmi_core) — sem banco."""
from datetime import date

import common  # noqa: F401  (ajusta sys.path)
from gwmi_core.analytics import (INDICATION, INSUFFICIENT, NO_SIGNAL, SIGNAL, composite_index, cycle_phase,
                                 evaluate_rule, pearson, trend_arrow, window_change)


def _s(vals, y=2024):
    return [(date(y + (i // 12), i % 12 + 1, 1), float(v)) for i, v in enumerate(vals)]


RULE = [{"label": "Exp ↓", "indicator": "EXP", "geo": "{market}", "test": "down", "window": 3, "threshold": .02},
        {"label": "Imp ↓", "indicator": "IMP", "geo": "{market}", "test": "down", "window": 3, "threshold": .02},
        {"label": "Preço ↓", "indicator": "PRICE", "geo": "BRA", "test": "down", "window": 3, "threshold": .01},
        {"label": "Frete ↑", "indicator": "FREIGHT", "geo": "WLD", "test": "up", "window": 3, "threshold": .02}]


def test_trend_and_window():
    assert trend_arrow(.01) == "↑" and trend_arrow(-.01) == "↓" and trend_arrow(.001) == "→"
    assert abs(window_change([1, 1, 1, 2, 2, 2], 3) - 1.0) < 1e-9
    assert window_change([1, 2], 3) is None


def test_signal_all_conditions_met():
    down, up = _s([100] * 3 + [90] * 3), _s([100] * 3 + [110] * 3)
    series = {("EXP", "USA"): down, ("IMP", "USA"): down, ("PRICE", "BRA"): down, ("FREIGHT", "WLD"): up}
    assert evaluate_rule("r", RULE, "USA", series).result == SIGNAL


def test_signal_indication_and_none():
    down, up, flat = _s([100] * 3 + [90] * 3), _s([100] * 3 + [110] * 3), _s([100] * 6)
    s = {("EXP", "USA"): down, ("IMP", "USA"): down, ("PRICE", "BRA"): down, ("FREIGHT", "WLD"): flat}
    assert evaluate_rule("r", RULE, "USA", s).result == INDICATION
    s2 = {("EXP", "USA"): up, ("IMP", "USA"): up, ("PRICE", "BRA"): flat, ("FREIGHT", "WLD"): flat}
    assert evaluate_rule("r", RULE, "USA", s2).result == NO_SIGNAL


def test_missing_data_is_never_zero():
    down = _s([100] * 3 + [90] * 3)
    s = {("EXP", "MEX"): down, ("IMP", "MEX"): down}          # preço e frete sem série
    ev = evaluate_rule("r", RULE, "MEX", s)
    assert ev.unknown == 2 and ev.result == INSUFFICIENT


def test_cycle_phase_rule():
    rising = [100] * 54 + [101, 103, 105, 107, 109, 111, 113]
    assert cycle_phase(rising)[0] == "EXPANSÃO"
    falling_high = [100] * 54 + [130, 128, 126, 124, 122, 120, 118]
    assert cycle_phase(falling_high)[0] == "DESACELERAÇÃO"
    low_recovering = [100] * 54 + [80, 82, 84, 86, 88, 90, 92]
    assert cycle_phase(low_recovering)[0] == "RECUPERAÇÃO"


def test_composite_index_coverage_and_inversion():
    a = _s(list(range(1, 37)))
    b = _s(list(range(36, 0, -1)))
    comp = [{"indicator": "A", "geo": "WLD", "weight": 1}, {"indicator": "B", "geo": "WLD", "weight": 1, "invert": True},
            {"indicator": "C", "geo": "WLD", "weight": 1}]
    res = composite_index(comp, {("A", "WLD"): a, ("B", "WLD"): b})
    assert [m["indicator"] for m in res.missing] == ["C"]
    assert len(res.values) == 36 and res.values[-1] > res.values[0]   # B invertida reforça A


def test_pearson_requires_min_obs():
    assert pearson([1, 2, 3], [1, 2, 3]) is None
    assert abs(pearson([1, 2, 3, 4, 5, 6], [2, 4, 6, 8, 10, 12]) - 1) < 1e-9


def test_stale_series_does_not_count_as_evidence():
    from gwmi_core.analytics import evaluate_condition
    s = {("IMP_TOTAL_WOOD", "CHN"): [(date(2024, m, 1), 100.0 + m) for m in range(1, 13)]}
    c = {"indicator": "IMP_TOTAL_WOOD", "geo": "{market}", "test": "up", "window": 3, "threshold": 0.01}
    fresh = evaluate_condition(c, "CHN", s, as_of=date(2025, 1, 1))
    old = evaluate_condition(c, "CHN", s, as_of=date(2026, 9, 1))
    assert fresh.met is True and fresh.stale is False
    assert old.met is None and old.stale is True and old.last_period == date(2024, 12, 1)
