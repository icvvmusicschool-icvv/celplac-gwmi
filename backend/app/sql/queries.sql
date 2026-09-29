-- Consultas nomeadas da API. Formato: "-- name: <nome>" seguido do SQL.
-- Parâmetros psycopg (%(x)s) SEMPRE com cast explícito para resolução de tipos.
-- tests/test_api_sql.py executa cada consulta contra um banco populado.

-- name: api_settings
SELECT value FROM meta.setting WHERE key = 'api'

-- name: sources_by_ids
SELECT source_id, name, url, source_type, periodicity, methodology, license_note, reliability
FROM meta.source WHERE source_id = ANY(%(ids)s::text[])

-- name: sources_list
SELECT s.*, q.integration_status, q.is_simulated AS has_simulated, q.last_period, q.last_collected, q.last_run_status
FROM meta.source s LEFT JOIN dq.v_source_quality q USING (source_id)
ORDER BY s.source_type, s.name

-- name: source_quality
SELECT * FROM dq.v_source_quality ORDER BY integration_status, source_id

-- name: rule_status
SELECT * FROM dq.v_rule_status ORDER BY passed NULLS FIRST, severity, rule_id

-- name: indicators_list
SELECT i.*, l.period AS last_period, l.value AS last_value, l.is_simulated
FROM dw.dim_indicator i LEFT JOIN mart.v_series_latest l
  ON l.indicator_code = i.indicator_code AND l.geo_iso3 = (
       SELECT geo_iso3 FROM mart.v_series_latest x WHERE x.indicator_code = i.indicator_code ORDER BY x.period DESC LIMIT 1)
ORDER BY i.category, i.indicator_code

-- name: pulse
SELECT * FROM mart.v_series_latest
WHERE pulse_key IS NOT NULL
ORDER BY array_position(ARRAY['WOOD','PLYWOOD','VENEER','CONSTRUCTION','TRUCKING','SHIPPING','USD/BRL','CHINA','USA','EUROPE'], pulse_key)

-- name: series_history
SELECT indicator_code, geo_iso3, period, value, is_simulated, source_id
FROM mart.v_series_monthly
WHERE indicator_code = ANY(%(codes)s::text[]) AND period >= %(since)s::date
ORDER BY indicator_code, geo_iso3, period

-- name: series_monthly
SELECT period, value, n_obs, is_simulated, source_id, run_id
FROM mart.v_series_monthly
WHERE indicator_code = %(code)s::text AND geo_iso3 = %(geo)s::char(3)
  AND period BETWEEN %(from)s::date AND %(to)s::date
ORDER BY period

-- name: series_native
SELECT period, value, obs_status, is_simulated, source_id, run_id, obs_id
FROM mart.v_series_effective
WHERE indicator_code = %(code)s::text AND geo_iso3 = %(geo)s::char(3)
  AND period BETWEEN %(from)s::date AND %(to)s::date
ORDER BY period

-- name: series_latest
SELECT * FROM mart.v_series_latest
WHERE (%(category)s::text IS NULL OR category = %(category)s::text)
  AND (%(geo)s::char(3) IS NULL OR geo_iso3 = %(geo)s::char(3))
ORDER BY category, indicator_code, geo_iso3

-- name: exports_summary
SELECT * FROM mart.exports_summary(%(end)s::date, %(months)s::int, %(family)s::text)

-- name: export_destinations
SELECT * FROM mart.export_destinations(%(end)s::date, %(months)s::int, %(family)s::text)

-- name: exports_by_hs6
SELECT * FROM mart.exports_by_hs6(%(end)s::date, %(months)s::int)

-- name: export_flows
SELECT * FROM mart.export_flows(%(end)s::date, %(months)s::int)

-- name: trade_monthly
SELECT * FROM mart.exports_monthly(%(family)s::text, %(partner)s::char(3), %(flow)s::char(1))

-- name: ncm_catalog
SELECT h.hs6, h.description_pt, h.product_code, p.family, p.name_pt AS product_name, h.is_verified,
       coalesce(json_agg(json_build_object('ncm8', n.ncm8, 'description_pt', n.description_pt, 'stat_unit', n.stat_unit_name))
                FILTER (WHERE n.ncm8 IS NOT NULL), '[]') AS ncm8
FROM dw.map_hs6_product h JOIN dw.dim_product p USING (product_code)
LEFT JOIN dw.dim_ncm n ON n.hs6 = h.hs6
GROUP BY h.hs6, h.description_pt, h.product_code, p.family, p.name_pt, h.is_verified
ORDER BY h.hs6

-- name: ncm_search
SELECT * FROM mart.ncm_search(%(q)s::text, %(family)s::text, %(partner)s::char(3), %(year)s::int, %(month)s::int, %(flow)s::char(1))

-- name: competitors
SELECT * FROM mart.competitors(%(hs4)s::text, %(year)s::int)

-- name: fx_stats
SELECT * FROM mart.v_fx_stats ORDER BY indicator_code

-- name: correlation_pair
SELECT a.period, a.value AS x, b.value AS y, (a.is_simulated OR b.is_simulated) AS is_simulated
FROM mart.v_series_monthly a
JOIN mart.v_series_monthly b ON b.period = a.period AND b.indicator_code = %(y_code)s::text AND b.geo_iso3 = %(y_geo)s::char(3)
WHERE a.indicator_code = %(x_code)s::text AND a.geo_iso3 = %(x_geo)s::char(3)
  AND a.period >= %(since)s::date
ORDER BY a.period

-- name: macro_latest
SELECT l.*, c.name_pt AS geo_name FROM mart.v_series_latest l JOIN dw.dim_country c ON c.iso3 = l.geo_iso3
WHERE l.category = 'macro' ORDER BY c.name_pt, l.indicator_code

-- name: market_cycle
SELECT * FROM mart.market_cycle(%(threshold)s::numeric)

-- name: signals_latest
SELECT DISTINCT ON (s.rule_id, s.market_iso3)
       s.rule_id, r.name AS rule_name, r.tone, s.market_iso3, c.name_pt AS market_name, s.as_of,
       s.conditions_met, s.conditions_total, s.result, s.detail, s.is_simulated, s.computed_at
FROM intel.signal_state s
JOIN intel.signal_rule r ON r.rule_id = s.rule_id AND r.version = s.rule_version
JOIN dw.dim_country c ON c.iso3 = s.market_iso3
ORDER BY s.rule_id, s.market_iso3, s.as_of DESC, s.is_simulated ASC, s.rule_version DESC

-- name: events
SELECT * FROM intel.geo_event
WHERE (%(category)s::text IS NULL OR category = %(category)s::text)
  AND (%(country)s::char(3) IS NULL OR %(country)s::char(3) = ANY(countries))
  AND (NOT is_simulated OR %(allow_sim)s::boolean)
ORDER BY event_date DESC LIMIT %(limit)s::int

-- name: news
SELECT * FROM intel.news_item
WHERE (%(impact_class)s::text IS NULL OR impact_class::text = %(impact_class)s::text)
  AND (NOT is_simulated OR %(allow_sim)s::boolean)
ORDER BY published_at DESC LIMIT %(limit)s::int

-- name: alerts_open
SELECT * FROM intel.alert WHERE resolved_at IS NULL AND (NOT is_simulated OR %(allow_sim)s::boolean)
ORDER BY created_at DESC LIMIT 50

-- name: index_config
SELECT * FROM intel.index_config
WHERE (%(config_id)s::bigint IS NULL AND is_default) OR config_id = %(config_id)s::bigint
ORDER BY is_default DESC LIMIT 1

-- name: index_series
SELECT m.indicator_code, m.geo_iso3, m.period, m.value, m.is_simulated
FROM mart.v_series_monthly m
JOIN unnest(%(codes)s::text[], %(geos)s::text[]) AS k(code, geo) ON k.code = m.indicator_code AND k.geo = m.geo_iso3
WHERE m.value IS NOT NULL
ORDER BY 1, 2, 3

-- name: index_config_insert
INSERT INTO intel.index_config (name, components, created_by, note)
VALUES (%(name)s::text, %(components)s::jsonb, %(created_by)s::text, %(note)s::text)
RETURNING config_id, created_at

-- name: trace_trade
SELECT f.*, r.job, r.params, r.started_at AS run_started_at, r.finished_at AS run_finished_at, r.status AS run_status,
       s.name AS source_name, s.url AS source_url, s.methodology, s.periodicity,
       (SELECT json_agg(json_build_object('uri', i.uri, 'sha256', i.content_sha256, 'bytes', i.bytes, 'fetched_at', i.fetched_at))
          FROM raw.ingestion i WHERE i.run_id = f.run_id) AS raw_files,
       (SELECT json_agg(json_build_object('version', v.version, 'value_usd_fob', v.value_usd_fob, 'collected_at', v.collected_at,
                                          'superseded_at', v.superseded_at, 'run_id', v.run_id) ORDER BY v.version)
          FROM dw.fact_trade v
         WHERE v.flow = f.flow AND v.period = f.period AND v.reporter_iso3 = f.reporter_iso3 AND v.partner_iso3 = f.partner_iso3
           AND v.ncm8 = f.ncm8 AND v.uf = f.uf AND v.urf_code = f.urf_code AND v.via_code = f.via_code
           AND v.source_id = f.source_id AND v.is_simulated = f.is_simulated) AS versions
FROM dw.fact_trade f
JOIN meta.etl_run r ON r.run_id = f.run_id
JOIN meta.source s ON s.source_id = f.source_id
WHERE f.trade_id = %(id)s::bigint

-- name: trace_series
SELECT f.*, i.name_pt, i.unit, i.formula, i.kind, r.job, r.params, r.finished_at AS run_finished_at,
       s.name AS source_name, s.url AS source_url, s.methodology, s.periodicity,
       (SELECT json_agg(json_build_object('uri', x.uri, 'sha256', x.content_sha256, 'bytes', x.bytes, 'fetched_at', x.fetched_at))
          FROM raw.ingestion x WHERE x.run_id = f.run_id) AS raw_files,
       (SELECT json_agg(json_build_object('version', v.version, 'value', v.value, 'collected_at', v.collected_at,
                                          'superseded_at', v.superseded_at) ORDER BY v.version)
          FROM dw.fact_series v WHERE v.indicator_code = f.indicator_code AND v.geo_iso3 = f.geo_iso3
           AND v.period = f.period AND v.source_id = f.source_id AND v.is_simulated = f.is_simulated) AS versions
FROM mart.v_series_effective f
JOIN dw.dim_indicator i ON i.indicator_code = f.indicator_code
JOIN meta.etl_run r ON r.run_id = f.run_id
JOIN meta.source s ON s.source_id = f.source_id
WHERE f.indicator_code = %(code)s::text AND f.geo_iso3 = %(geo)s::char(3)
  AND (%(period)s::date IS NULL OR f.period = %(period)s::date)
ORDER BY f.period DESC LIMIT 1

-- name: runs_recent
SELECT run_id, source_id, job, status, started_at, finished_at, rows_staged, rows_rejected, rows_inserted,
       rows_revised, rows_unchanged, is_simulated, error
FROM meta.etl_run ORDER BY run_id DESC LIMIT %(limit)s::int
