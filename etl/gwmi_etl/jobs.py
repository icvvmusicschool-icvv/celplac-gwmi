"""Jobs que não baixam dados: indicadores derivados, sinais e importação de inteligência."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date
from pathlib import Path

from gwmi_core.analytics import evaluate_rule

from .db import Database
from .pipeline import finish_run, start_run


def run_derive(db: Database, group: str) -> dict:
    """Recalcula indicadores derivados do DW (fórmulas em dim_indicator.formula)."""
    if group == "fx_cross":  # taxas cruzadas MXN/CNY (PTAX ÷ Fed H.10) — migração 0015
        sim = not db.scalar("""SELECT EXISTS (SELECT 1 FROM dw.fact_series WHERE is_current AND NOT is_simulated
                                             AND indicator_code = 'FX_USD_BRL')""")
    else:
        sim = bool(db.scalar("SELECT mart.derive_group_is_simulated(%(g)s)", {"g": group}))
    run_id = start_run(db, "gwmi_calc", f"derive.{group}", {"group": group}, sim)
    try:
        if group == "fx_cross":
            staged = int(db.scalar("SELECT mart.derive_fx_cross(%(r)s)", {"r": run_id}))
        else:
            staged = int(db.scalar("SELECT mart.derive_trade_series(%(r)s, %(g)s)", {"r": run_id, "g": group}))
        res = db.query("SELECT * FROM dw.merge_series(%(r)s)", {"r": run_id})[0]
        finish_run(db, run_id, "success", staged, 0)
        return {"run_id": run_id, "group": group, "is_simulated": sim, "staged": staged, **res}
    except Exception as e:
        db.execute("DELETE FROM stg.series WHERE run_id = %(r)s", {"r": run_id})
        finish_run(db, run_id, "failed", 0, 0, f"{type(e).__name__}: {e}")
        raise


def _load_monthly(db: Database, keys: set[tuple[str, str]]) -> tuple[dict, dict]:
    series: dict[tuple[str, str], list[tuple[date, float]]] = defaultdict(list)
    simflag: dict[tuple[str, str], bool] = {}
    if not keys:
        return series, simflag
    inds = sorted({k[0] for k in keys})
    rows = db.query(
        """SELECT indicator_code, geo_iso3, period, value, is_simulated FROM mart.v_series_monthly
           WHERE indicator_code = ANY(%(i)s) AND value IS NOT NULL ORDER BY indicator_code, geo_iso3, period""",
        {"i": inds})
    for r in rows:
        k = (r["indicator_code"], r["geo_iso3"].strip())
        if k in keys:
            series[k].append((r["period"], float(r["value"])))
            simflag[k] = simflag.get(k, False) or bool(r["is_simulated"])
    return series, simflag


def run_signals(db: Database, as_of: date | None = None) -> list[dict]:
    """Avalia as regras ativas de early warning e grava intel.signal_state."""
    rules = db.query("""SELECT DISTINCT ON (rule_id) * FROM intel.signal_rule WHERE is_active
                        ORDER BY rule_id, version DESC""")
    keys: set[tuple[str, str]] = set()
    for rule in rules:
        conds = rule["conditions"] if isinstance(rule["conditions"], list) else json.loads(rule["conditions"])
        rule["conditions"] = conds
        for m in rule["markets"]:
            for c in conds:
                keys.add((c["indicator"], str(c.get("geo", "{market}")).replace("{market}", m.strip())))
    series, simflag = _load_monthly(db, keys)
    as_of = as_of or date.today().replace(day=1)
    out = []
    for rule in rules:
        for m in rule["markets"]:
            m = m.strip()
            ev = evaluate_rule(rule["rule_id"], rule["conditions"], m, series, rule["min_met_for_indication"], as_of)
            used = [(c.indicator, c.geo) for c in ev.conditions]
            sim = any(simflag.get(k, False) for k in used)
            detail = [{"label": c.label, "indicator": c.indicator, "geo": c.geo, "test": c.test, "met": c.met,
                       "observed": c.observed, "threshold": c.threshold, "n_obs": c.n_obs,
                       "last_period": c.last_period, "stale": c.stale,
                       "is_simulated": simflag.get((c.indicator, c.geo))} for c in ev.conditions]
            db.execute(
                """INSERT INTO intel.signal_state (rule_id, rule_version, market_iso3, as_of, conditions_met,
                          conditions_total, detail, result, is_simulated)
                   VALUES (%(r)s, %(v)s, %(m)s, %(a)s, %(met)s, %(tot)s, %(d)s::jsonb, %(res)s, %(sim)s)
                   ON CONFLICT (rule_id, rule_version, market_iso3, as_of, is_simulated) DO UPDATE
                   SET conditions_met = EXCLUDED.conditions_met, detail = EXCLUDED.detail,
                       result = EXCLUDED.result, computed_at = now()""",
                {"r": rule["rule_id"], "v": rule["version"], "m": m, "a": as_of, "met": ev.met,
                 "tot": ev.total, "d": json.dumps(detail, default=str), "res": ev.result, "sim": sim})
            out.append({"rule": rule["rule_id"], "market": m, "result": ev.result, "met": ev.met,
                        "unknown": ev.unknown, "is_simulated": sim})
    return out


# ----------------------------------------------------------------------
# Inteligência: eventos e notícias (JSON Lines) — curadoria do analista
# ----------------------------------------------------------------------
EVENT_REQUIRED = ("event_id", "category", "title", "event_date", "evidence", "source_name")
NEWS_REQUIRED = ("published_at", "title", "source_name", "category", "impact_class")


def import_intel(db: Database, path: Path, kind: str, is_simulated: bool = False) -> dict:
    ok, bad = 0, []
    for i, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        o = json.loads(line)
        req = EVENT_REQUIRED if kind == "events" else NEWS_REQUIRED
        miss = [k for k in req if not o.get(k)]
        if miss:
            bad.append({"line": i, "missing": miss})
            continue
        if kind == "events":
            if len(str(o["evidence"]).strip()) < 10:
                bad.append({"line": i, "reason": "evidência insuficiente — evento não registrado"})
                continue
            db.execute(
                """INSERT INTO intel.geo_event (event_id, category, title, event_date, countries, hs6_affected,
                       products_text, routes, potential_impact, confidence, evidence, source_name, source_url,
                       impact_class, status, is_simulated)
                   VALUES (%(event_id)s, %(category)s, %(title)s, %(event_date)s, %(countries)s, %(hs6)s,
                       %(products_text)s, %(routes)s, %(potential_impact)s::intel.impact_level,
                       %(confidence)s::intel.confidence, %(evidence)s, %(source_name)s, %(source_url)s,
                       %(impact_class)s::intel.impact_class, %(status)s, %(sim)s)
                   ON CONFLICT (event_id) DO UPDATE SET title = EXCLUDED.title, potential_impact = EXCLUDED.potential_impact,
                       confidence = EXCLUDED.confidence, evidence = EXCLUDED.evidence, status = EXCLUDED.status,
                       impact_class = EXCLUDED.impact_class, updated_at = now()""",
                {"countries": o.get("countries", []), "hs6": o.get("hs6_affected", []),
                 "products_text": o.get("products_text"), "routes": o.get("routes"),
                 "potential_impact": o.get("potential_impact", "INDETERMINADO"),
                 "confidence": o.get("confidence", "BAIXA"), "source_url": o.get("source_url"),
                 "impact_class": o.get("impact_class", "monitoramento"), "status": o.get("status", "aberto"),
                 "sim": is_simulated, **{k: o[k] for k in EVENT_REQUIRED}})
        else:
            key = o.get("url") or f"{o['source_name']}|{o['title']}|{o['published_at']}"
            db.execute(
                """INSERT INTO intel.news_item (published_at, title, source_name, url, url_sha256, country_iso3,
                       category, summary, products_text, hs6_affected, impact_class, potential_impact,
                       classified_by, event_id, is_simulated)
                   VALUES (%(published_at)s, %(title)s, %(source_name)s, %(url)s, %(h)s, %(countries)s, %(category)s,
                       %(summary)s, %(products_text)s, %(hs6)s, %(impact_class)s::intel.impact_class,
                       %(potential_impact)s::intel.impact_level, %(by)s, %(event_id)s, %(sim)s)
                   ON CONFLICT (url_sha256) DO NOTHING""",
                {"h": hashlib.sha256(key.encode()).hexdigest(), "url": o.get("url"),
                 "countries": o.get("country_iso3", []), "summary": o.get("summary"),
                 "products_text": o.get("products_text"), "hs6": o.get("hs6_affected", []),
                 "potential_impact": o.get("potential_impact", "INDETERMINADO"),
                 "by": o.get("classified_by", "analyst"), "event_id": o.get("event_id"), "sim": is_simulated,
                 **{k: o[k] for k in NEWS_REQUIRED}})
        ok += 1
    return {"imported": ok, "rejected": bad}
