"""Funções analíticas puras (sem I/O) compartilhadas por ETL e API.

Princípios:
  * Um SINAL não é previsão. Resultados possíveis: SINAL, INDICAÇÃO,
    SEM SINAL, EVIDÊNCIA INSUFICIENTE.
  * Dado ausente nunca vira zero: condição sem série = "sem dado".
  * O índice composto reporta cobertura (quais componentes entraram).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from math import sqrt
from statistics import mean, pstdev
from typing import Iterable, Mapping, Sequence

Series = Sequence[tuple[date, float]]  # (período, valor) em ordem crescente

SIGNAL = "SINAL"
INDICATION = "INDICAÇÃO"
NO_SIGNAL = "SEM SINAL"
INSUFFICIENT = "EVIDÊNCIA INSUFICIENTE"


def trend_arrow(change: float | None, threshold: float = 0.005) -> str | None:
    if change is None:
        return None
    if change > threshold:
        return "↑"
    if change < -threshold:
        return "↓"
    return "→"


def window_change(values: Sequence[float], window: int) -> float | None:
    """Variação da média das últimas `window` observações vs. as `window` anteriores."""
    if window < 1 or len(values) < 2 * window:
        return None
    cur = mean(values[-window:])
    prev = mean(values[-2 * window:-window])
    if prev == 0:
        return None
    return cur / prev - 1


# ----------------------------------------------------------------------
# Early warning
# ----------------------------------------------------------------------
@dataclass
class ConditionResult:
    label: str
    indicator: str
    geo: str
    test: str
    met: bool | None          # None = sem dado suficiente
    observed: float | None    # variação ou valor usado no teste
    threshold: float | None
    n_obs: int
    last_period: date | None = None
    stale: bool = False       # último dado mais antigo que o limite → tratado como "sem dado"


@dataclass
class SignalEvaluation:
    rule_id: str
    market: str
    result: str
    met: int
    unknown: int
    total: int
    conditions: list[ConditionResult] = field(default_factory=list)


def _months_between(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def evaluate_condition(cond: Mapping, market: str, series: Mapping[tuple[str, str], Series],
                       as_of: date | None = None, max_age_months: int = 6) -> ConditionResult:
    """Com `as_of`, série cujo último dado tem mais de `max_age_months` meses não conta:
    a condição fica "sem dado" (defasada), em vez de refletir um mercado de anos atrás."""
    geo = str(cond.get("geo", "{market}")).replace("{market}", market)
    ind = cond["indicator"]
    test = cond["test"]
    window = int(cond.get("window", 3))
    th = cond.get("threshold")
    th = float(th) if th is not None else None
    s = series.get((ind, geo)) or []
    s = [(p, v) for p, v in s if v is not None and (as_of is None or p <= as_of)]
    values = [v for _, v in s]
    last = s[-1][0] if s else None
    observed: float | None = None
    met: bool | None = None
    if as_of is not None and last is not None and _months_between(last, as_of) > max_age_months:
        return ConditionResult(cond.get("label", ind), ind, geo, test, None, None, th, len(values), last, True)
    if test in ("up", "down", "stable"):
        observed = window_change(values, window)
        t = th if th is not None else 0.0
        if observed is not None:
            met = {"up": observed > t, "down": observed < -t, "stable": abs(observed) <= t}[test]
    elif test in ("positive", "negative"):
        if values:
            observed = values[-1]
            met = observed > 0 if test == "positive" else observed < 0
    else:
        raise ValueError(f"teste desconhecido: {test}")
    return ConditionResult(cond.get("label", ind), ind, geo, test, met, observed, th, len(values), last)


def evaluate_rule(rule_id: str, conditions: Sequence[Mapping], market: str,
                  series: Mapping[tuple[str, str], Series], min_met_for_indication: int = 3,
                  as_of: date | None = None, max_age_months: int = 6) -> SignalEvaluation:
    res = [evaluate_condition(c, market, series, as_of, max_age_months) for c in conditions]
    total = len(res)
    met = sum(1 for r in res if r.met is True)
    unknown = sum(1 for r in res if r.met is None)
    if unknown == 0:
        result = SIGNAL if met == total else INDICATION if met >= min_met_for_indication else NO_SIGNAL
    else:
        # só conclui "sem sinal" se, mesmo com os dados faltantes favoráveis, o limiar não seria atingido
        result = INSUFFICIENT if met + unknown >= min_met_for_indication else NO_SIGNAL
    return SignalEvaluation(rule_id, market, result, met, unknown, total, res)


# ----------------------------------------------------------------------
# Market cycle (mesma regra da função SQL mart.market_cycle)
# ----------------------------------------------------------------------
def cycle_phase(values: Sequence[float], momentum_threshold: float = 0.01,
                avg_window: int = 60, momentum_lag: int = 6) -> tuple[str, float | None, float | None]:
    if len(values) <= momentum_lag:
        return INSUFFICIENT, None, None
    last = values[-1]
    avg = mean(values[-avg_window:])
    base = values[-1 - momentum_lag]
    if avg == 0 or base == 0:
        return INSUFFICIENT, None, None
    level = last / avg - 1
    mom = last / base - 1
    t = momentum_threshold
    if level >= 0:
        phase = "EXPANSÃO" if mom > t else "DESACELERAÇÃO" if mom < -t else "PICO"
    else:
        phase = "RECUPERAÇÃO" if mom > t else "CONTRAÇÃO"
    return phase, level, mom


# ----------------------------------------------------------------------
# Índice composto configurável
# ----------------------------------------------------------------------
@dataclass
class IndexResult:
    periods: list[date]
    values: list[float]
    used: list[dict]
    missing: list[dict]
    total_weight: float


def composite_index(components: Iterable[Mapping], series: Mapping[tuple[str, str], Series],
                    min_obs: int = 24, base: float = 100.0, scale: float = 10.0) -> IndexResult:
    """z-score de cada componente sobre o seu próprio histórico, ponderado.

    O índice só é calculado nos períodos em que TODOS os componentes usados
    têm observação (sem preenchimento artificial). Componentes sem histórico
    mínimo são excluídos e listados em `missing`.
    """
    used, missing, zs = [], [], []
    for c in components:
        w = float(c.get("weight", 0))
        if w <= 0:
            continue
        key = (c["indicator"], c.get("geo", "WLD"))
        s = [(p, v) for p, v in (series.get(key) or []) if v is not None]
        if len(s) < min_obs:
            missing.append({**c, "reason": f"histórico insuficiente ({len(s)} obs.)"})
            continue
        vals = [v for _, v in s]
        m, sd = mean(vals), pstdev(vals)
        if sd == 0:
            missing.append({**c, "reason": "série constante"})
            continue
        sign = -1.0 if c.get("invert") else 1.0
        zs.append((w, {p: sign * (v - m) / sd for p, v in s}))
        used.append(dict(c))
    if not zs:
        return IndexResult([], [], used, missing, 0.0)
    common = sorted(set.intersection(*(set(z.keys()) for _, z in zs)))
    tw = sum(w for w, _ in zs)
    vals = [base + scale * sum(w * z[p] for w, z in zs) / tw for p in common]
    return IndexResult(common, vals, used, missing, tw)


def annualized_vol(monthly_values: Sequence[float], months: int = 12) -> float | None:
    from math import log
    v = [x for x in monthly_values if x and x > 0]
    if len(v) < months + 1:
        return None
    r = [log(v[i] / v[i - 1]) for i in range(len(v) - months, len(v))]
    m = mean(r)
    return sqrt(sum((x - m) ** 2 for x in r) / (len(r) - 1)) * sqrt(12)


def pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Correlação — nunca apresentada como causalidade."""
    n = min(len(xs), len(ys))
    if n < 6:
        return None
    xs, ys = xs[-n:], ys[-n:]
    mx, my = mean(xs), mean(ys)
    sxy = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    sxx = sum((a - mx) ** 2 for a in xs)
    syy = sum((b - my) ** 2 for b in ys)
    if sxx == 0 or syy == 0:
        return None
    return sxy / sqrt(sxx * syy)
