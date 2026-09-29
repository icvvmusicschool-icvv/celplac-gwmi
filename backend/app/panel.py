"""Dados do painel num único pacote (GET /v1/panel).

As mesmas três consultas alimentam o painel ao vivo (servido pela API) e o retrato
publicado sem API (frontend/painel-real/build.py). Só dado real: tudo filtra
`is_simulated = false` ou usa as views/funções mart.* em modo real.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any

SQL_SERIES = """
SELECT now()::text AS asof, coalesce(jsonb_agg(jsonb_build_object('i',m.indicator_code,'g',m.geo_iso3,'src',m.src,'run',m.run,'at',m.at,'v',m.v)
       ORDER BY m.indicator_code, m.geo_iso3), '[]'::jsonb) AS series
FROM (SELECT indicator_code, geo_iso3, string_agg(DISTINCT source_id, ',') src, max(run_id) run, max(collected_at)::date::text at,
             string_agg(to_char(period,'YYYY-MM')||'='||round(value, CASE WHEN abs(value)>=1000 THEN 0 WHEN abs(value)>=10 THEN 2 ELSE 4 END)::text, ';' ORDER BY period) v
      FROM mart.v_series_monthly
      WHERE NOT is_simulated AND period >= '2013-01-01' AND value IS NOT NULL
        AND NOT (indicator_code = 'EXP_BR_M3' AND geo_iso3 NOT IN ('WLD','EUU','USA'))
      GROUP BY 1,2) m
"""

SQL_META = """
SELECT jsonb_build_object(
 'indicators',(SELECT jsonb_agg(to_jsonb(i) - 'created_at' - 'updated_at') FROM dw.dim_indicator i),
 'sources',(SELECT jsonb_agg(to_jsonb(s)) FROM meta.source s),
 'source_quality',(SELECT jsonb_agg(to_jsonb(q)) FROM dq.v_source_quality q),
 'rules',(SELECT jsonb_agg(to_jsonb(r)) FROM dq.v_rule_status r),
 'latest',(SELECT jsonb_agg(to_jsonb(l) - 'name_pt' - 'unit' - 'category' - 'pulse_key' - 'kind' - 'polarity') FROM mart.v_series_latest l
           WHERE NOT is_simulated AND NOT (indicator_code IN ('EXP_BR_VALUE','EXP_BR_M3','IMP_TOTAL_WOOD') AND geo_iso3 NOT IN ('WLD','EUU','USA'))),
 'fx_stats',(SELECT jsonb_agg(to_jsonb(f)) FROM mart.v_fx_stats f WHERE NOT is_simulated),
 'cycle',(SELECT jsonb_agg(to_jsonb(c)) FROM mart.market_cycle() c WHERE NOT c.is_simulated),
 'signal_rules',(SELECT jsonb_agg(to_jsonb(r)) FROM intel.signal_rule r WHERE is_active),
 'signals',(SELECT jsonb_agg(to_jsonb(s)) FROM intel.signal_state s WHERE NOT is_simulated
            AND (rule_id, rule_version) IN (SELECT rule_id, version FROM intel.signal_rule WHERE is_active)
            AND as_of = (SELECT max(as_of) FROM intel.signal_state WHERE NOT is_simulated)),
 'index_configs',(SELECT jsonb_agg(to_jsonb(x)) FROM intel.index_config x),
 'countries',(SELECT jsonb_agg(jsonb_build_object('iso3',iso3,'name',name_pt,'region',region)) FROM dw.dim_country c WHERE NOT is_aggregate),
 'runs',(SELECT jsonb_agg(to_jsonb(r) ORDER BY run_id) FROM (SELECT run_id, source_id, job, status, started_at, finished_at, rows_staged
         FROM meta.etl_run WHERE NOT is_simulated) r),
 'raw',(SELECT jsonb_agg(jsonb_build_object('run',i.run_id,'src',i.source_id,'uri',i.uri,'sha',i.content_sha256,'bytes',i.bytes) ORDER BY i.run_id)
        FROM raw.ingestion i JOIN meta.etl_run r USING (run_id) WHERE NOT r.is_simulated),
 'migrations',(SELECT count(*) FROM meta.schema_migrations),
 'comp_years',(WITH cov AS (SELECT left(hs6,4) hs4, extract(year FROM period)::int yr, count(DISTINCT reporter_iso3) n
                            FROM mart.v_trade_effective WHERE flow='X' AND partner_iso3='WLD' GROUP BY 1,2),
                   pick AS (SELECT h.hs4, coalesce(
                              (SELECT max(c.yr) FROM cov c JOIN cov p ON p.hs4=c.hs4 AND p.yr=c.yr-1
                                WHERE c.hs4=h.hs4 AND c.yr < extract(year FROM current_date) AND c.n >= 0.9*p.n),
                              (SELECT max(yr) FROM cov WHERE hs4=h.hs4 AND yr < extract(year FROM current_date))) yr
                            FROM (SELECT DISTINCT hs4 FROM cov) h)
               SELECT jsonb_object_agg(pick.hs4, jsonb_build_object('yr',pick.yr,'n',c.n,'np',p.n,'partial', c.n < 0.9*coalesce(p.n,0)))
               FROM pick JOIN cov c ON c.hs4=pick.hs4 AND c.yr=pick.yr LEFT JOIN cov p ON p.hs4=pick.hs4 AND p.yr=pick.yr-1)
) AS meta
"""

SQL_TRADE = """
SELECT jsonb_build_object(
 'last_period', (SELECT mart.last_trade_period()),
 'summary', (SELECT jsonb_object_agg(coalesce(f,'all'), (SELECT to_jsonb(s) FROM mart.exports_summary(NULL,12,f) s LIMIT 1))
             FROM unnest(ARRAY[NULL,'plywood','veneer','lvl','sawnwood','panels']::text[]) f),
 'destinations', (SELECT jsonb_agg(to_jsonb(d) - 'lat' - 'lon' - 'net_kg') FROM mart.export_destinations(NULL,12,NULL) d),
 'destinations_plywood', (SELECT jsonb_agg(to_jsonb(d) - 'lat' - 'lon' - 'net_kg') FROM mart.export_destinations(NULL,12,'plywood') d),
 'by_hs6', (SELECT jsonb_agg(to_jsonb(h)) FROM mart.exports_by_hs6(NULL,12) h),
 'flows', (SELECT jsonb_agg(to_jsonb(f)) FROM mart.export_flows(NULL,12) f),
 'monthly', (SELECT jsonb_agg(to_jsonb(m)) FROM mart.exports_monthly(NULL,NULL,'X') m),
 'monthly_plywood', (SELECT jsonb_agg(to_jsonb(m)) FROM mart.exports_monthly('plywood',NULL,'X') m),
 'comp_4412', (SELECT jsonb_agg(to_jsonb(c)) FROM mart.competitors('4412',NULL) c),
 'comp_4408', (SELECT jsonb_agg(to_jsonb(c)) FROM mart.competitors('4408',NULL) c),
 'comp_4407', (SELECT jsonb_agg(to_jsonb(c)) FROM mart.competitors('4407',NULL) c),
 'ncm', (SELECT jsonb_agg(to_jsonb(n)) FROM mart.ncm_search(NULL,NULL,NULL,NULL,NULL,'X') n),
 'imp_br_share', (SELECT jsonb_agg(jsonb_build_object('iso3',reporter_iso3,'p',to_char(period,'YYYY-MM'),'w',w,'b',b))
                  FROM (SELECT reporter_iso3, period, sum(value_usd_fob) FILTER (WHERE partner_iso3='WLD') w,
                               sum(value_usd_fob) FILTER (WHERE partner_iso3='BRA') b
                        FROM mart.v_trade_effective WHERE flow='M' AND left(hs6,4)='4412' AND reporter_iso3<>'BRA'
                          AND period >= '2023-01-01' GROUP BY 1,2) x)
) AS trade
"""

_ORDER = {"cost_pressure": 0, "demand_expansion": 1, "market_pressure": 2}
_MK = ["BRA", "USA", "EUU", "MEX", "CHN", "ARG", "SAU"]


def _j(v: Any) -> Any:
    return json.loads(v) if isinstance(v, str) else v


def real_only(x: Any) -> Any:
    """Remove qualquer linha marcada is_simulated=true (listas) e anula blocos simulados (dicts).
    As views mart.* mostram DEMO quando ainda não há dado real; o painel nunca mostra DEMO."""
    if isinstance(x, list):
        return [real_only(i) for i in x if not (isinstance(i, dict) and i.get("is_simulated") is True)]
    if isinstance(x, dict):
        if x.get("is_simulated") is True:
            return None
        return {k: real_only(v) for k, v in x.items()}
    return x


def shape(asof: str, series: list, meta: dict, trade: dict) -> dict:
    """Converte o resultado das três consultas no formato que o painel lê (window.GWMI)."""
    trade, meta = real_only(trade or {}), real_only(meta or {})
    for k in ("destinations", "destinations_plywood", "by_hs6", "flows", "monthly", "monthly_plywood",
              "comp_4412", "comp_4408", "comp_4407", "ncm", "imp_br_share"):
        trade[k] = trade.get(k) or []
    trade["summary"] = trade.get("summary") or {}
    ind = {x["indicator_code"]: {"n": x["name_pt"], "u": x["unit"], "k": x["kind"], "f": x["frequency"], "c": x["category"],
                                 "s": x["source_id"], "r": x.get("source_ref"), "fo": x.get("formula"),
                                 "d": x.get("description"), "pol": x.get("polarity")} for x in meta["indicators"] or []}
    src = {x["source_id"]: {"name": x["name"], "url": x.get("url"), "m": x.get("methodology"), "lic": x.get("license_note")}
           for x in meta["sources"] or []}
    runs = {str(x["run_id"]): {"s": x["source_id"], "j": x["job"], "st": x["status"],
                               "f": x.get("finished_at") or x.get("started_at"), "n": x.get("rows_staged")}
            for x in meta["runs"] or []}
    raw = [{"run": x["run"], "uri": x["uri"], "sha": x["sha"], "bytes": x["bytes"]} for x in meta["raw"] or []]
    dq = [{"id": x["rule_id"], "sev": x["severity"], "desc": x["description"], "fail": x["failing"], "passed": x["passed"]}
          for x in meta["rules"] or []]
    sig = sorted(meta["signals"] or [], key=lambda s: (_ORDER.get(s["rule_id"], 9),
                                                       _MK.index(s["market_iso3"]) if s["market_iso3"] in _MK else 99))
    sigr = sorted(meta["signal_rules"] or [], key=lambda s: _ORDER.get(s["rule_id"], 9))
    return {"ASOF": asof, "S": series, "I": ind, "SRC": src, "SQ": meta["source_quality"] or [], "DQ": dq, "RUNS": runs,
            "RAW": raw, "LATEST": meta["latest"] or [], "FX": meta["fx_stats"] or [], "CYC": meta["cycle"] or [],
            "SIG": sig, "SIGR": sigr, "IDX": meta["index_configs"] or [],
            "C": {x["iso3"]: [x["name"], x["region"]] for x in meta["countries"] or []},
            "T": trade, "COMPY": meta.get("comp_years") or {}, "MIG": meta["migrations"]}


def build(repo) -> dict:
    with repo.pool.connection() as conn:
        r = conn.execute(SQL_SERIES).fetchone()
        meta = _j(conn.execute(SQL_META).fetchone()["meta"])
        trade = _j(conn.execute(SQL_TRADE).fetchone()["trade"])
    return shape(r["asof"], _j(r["series"]), meta, trade)


class Cache:
    """O pacote leva ~1–2 s para montar e só muda quando há carga nova: guarda por `ttl` segundos."""

    def __init__(self, ttl: int = 600):
        self.ttl, self.at, self.data, self.lock = ttl, 0.0, None, threading.Lock()

    def get(self, repo, force: bool = False) -> dict:
        with self.lock:
            if force or self.data is None or time.time() - self.at > self.ttl:
                self.data, self.at = build(repo), time.time()
            return self.data


CACHE = Cache()
