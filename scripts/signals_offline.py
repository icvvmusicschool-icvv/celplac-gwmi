"""Calcula os sinais de early warning fora do ETL, a partir de um extrato das séries,
e gera o SQL que grava intel.signal_state. Usado quando o banco (ex.: Neon) não é
alcançável pelo ambiente que roda Python; a lógica é a MESMA de gwmi_core.analytics.evaluate_rule.

Entrada (JSON): {"as_of": "AAAA-MM-01", "rules": [...signal_rule...],
                 "series": [{"i": indicador, "g": geo, "v": "AAAA-MM=valor;...", "sim": bool}, ...]}
O extrato vem de mart.v_series_monthly (ver SQL no README). Séries ausentes do extrato
= sem dado → a condição fica "desconhecida" e o resultado pode ser EVIDÊNCIA INSUFICIENTE.
Uso: python signals_offline.py extrato.json > signals.sql
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
from gwmi_core.analytics import evaluate_rule  # noqa: E402


def load(payload: dict):
    series, sim = {}, {}
    for s in payload["series"]:
        pts = []
        for kv in s["v"].split(";"):
            p, v = kv.split("=")
            pts.append((date(int(p[:4]), int(p[5:7]), 1), float(v)))
        series[(s["i"], s["g"])] = pts
        sim[(s["i"], s["g"])] = bool(s.get("sim"))
    return series, sim


def q(x) -> str:
    return "NULL" if x is None else "'" + str(x).replace("'", "''") + "'"


def main(path: str) -> None:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    series, simflag = load(payload)
    as_of = payload["as_of"]
    out = []
    for rule in payload["rules"]:
        for m in rule["markets"]:
            ev = evaluate_rule(rule["rule_id"], rule["conditions"], m, series, rule["min_met_for_indication"],
                               date.fromisoformat(as_of))
            used = [(c.indicator, c.geo) for c in ev.conditions]
            sim = any(simflag.get(k, False) for k in used)
            detail = [{"label": c.label, "indicator": c.indicator, "geo": c.geo, "test": c.test, "met": c.met,
                       "observed": c.observed, "threshold": c.threshold, "n_obs": c.n_obs,
                       "last_period": c.last_period, "stale": c.stale, "is_simulated": simflag.get((c.indicator, c.geo))} for c in ev.conditions]
            out.append(
                "INSERT INTO intel.signal_state (rule_id, rule_version, market_iso3, as_of, conditions_met, conditions_total,"
                " detail, result, is_simulated) VALUES "
                f"({q(rule['rule_id'])}, {rule['version']}, {q(m)}, {q(as_of)}, {ev.met}, {ev.total}, "
                f"{q(json.dumps(detail, ensure_ascii=False, default=str))}::jsonb, {q(ev.result)}, {str(sim).lower()}) "
                "ON CONFLICT (rule_id, rule_version, market_iso3, as_of, is_simulated) DO UPDATE SET "
                "conditions_met = EXCLUDED.conditions_met, detail = EXCLUDED.detail, result = EXCLUDED.result, computed_at = now()")
            stale = [c.indicator for c in ev.conditions if c.stale]
            print(f"-- {rule['rule_id']:<17} {m}: {ev.result} ({ev.met}/{ev.total}, {ev.unknown} sem dado"
                  f"{', defasado: ' + ','.join(stale) if stale else ''})", file=sys.stderr)
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1])
