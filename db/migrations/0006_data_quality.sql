-- =====================================================================
-- CELPLAC GWMI · 0006 · Qualidade de dados
-- Regras declarativas: cada regra é um SELECT que devolve
--   (failing bigint, sample jsonb)
-- executado por dq.run_checks(). Resultado fica historizado em dq.result.
-- =====================================================================
CREATE TABLE dq.rule (
    rule_id     text PRIMARY KEY,
    dataset     text NOT NULL CHECK (dataset IN ('trade','series','intel')),
    severity    text NOT NULL CHECK (severity IN ('error','warn')),
    description text NOT NULL,
    check_sql   text NOT NULL,
    is_active   boolean NOT NULL DEFAULT true
);

CREATE TABLE dq.result (
    result_id   bigserial PRIMARY KEY,
    run_id      bigint REFERENCES meta.etl_run(run_id) ON DELETE SET NULL,
    rule_id     text NOT NULL REFERENCES dq.rule(rule_id),
    checked_at  timestamptz NOT NULL DEFAULT now(),
    failing     bigint NOT NULL,
    passed      boolean NOT NULL,
    sample      jsonb
);
CREATE INDEX dq_result_rule_idx ON dq.result (rule_id, checked_at DESC);

CREATE OR REPLACE FUNCTION dq.run_checks(p_run bigint DEFAULT NULL, p_dataset text DEFAULT NULL)
RETURNS TABLE (rule_id text, severity text, failing bigint, passed boolean)
LANGUAGE plpgsql AS $$
DECLARE r record; v_fail bigint; v_sample jsonb;
BEGIN
    FOR r IN SELECT * FROM dq.rule WHERE is_active AND (p_dataset IS NULL OR dataset = p_dataset) ORDER BY rule_id LOOP
        EXECUTE r.check_sql INTO v_fail, v_sample;
        v_fail := coalesce(v_fail, 0);
        INSERT INTO dq.result (run_id, rule_id, failing, passed, sample)
        VALUES (p_run, r.rule_id, v_fail, v_fail = 0, v_sample);
        rule_id := r.rule_id; severity := r.severity; failing := v_fail; passed := (v_fail = 0);
        RETURN NEXT;
    END LOOP;
END $$;

INSERT INTO dq.rule (rule_id, dataset, severity, description, check_sql) VALUES
('trade.non_negative', 'trade', 'error', 'Valor FOB, kg e quantidade não podem ser negativos',
 $q$SELECT count(*), jsonb_agg(to_jsonb(x)) FILTER (WHERE x.rn <= 5) FROM (
      SELECT trade_id, period, ncm8, value_usd_fob, net_kg, qty_stat, row_number() OVER () rn
      FROM dw.fact_trade WHERE is_current AND (value_usd_fob < 0 OR net_kg < 0 OR qty_stat < 0)) x$q$),
('trade.unmapped_country', 'trade', 'warn', 'Linhas com país não mapeado (XXX) — atualizar tabela PAIS',
 $q$SELECT count(*), jsonb_agg(DISTINCT ncm8) FROM dw.fact_trade WHERE is_current AND (partner_iso3 = 'XXX' OR reporter_iso3 = 'XXX')$q$),
('trade.m3_unavailable', 'trade', 'warn', 'Linhas sem volume em m³ (sem unidade m³ e sem densidade cadastrada)',
 $q$SELECT count(*), jsonb_agg(DISTINCT hs6) FROM dw.fact_trade WHERE is_current AND qty_m3_method = 'unavailable'$q$),
('trade.unclassified_hs6', 'trade', 'warn', 'SH6 sem produto associado em map_hs6_product',
 $q$SELECT count(DISTINCT f.hs6), jsonb_agg(DISTINCT f.hs6) FROM dw.fact_trade f
     LEFT JOIN dw.map_hs6_product h ON h.hs6 = f.hs6
     WHERE f.is_current AND h.hs6 IS NULL AND right(f.hs6, 2) <> '00'$q$),
('trade.price_outlier', 'trade', 'warn', 'Preço implícito (US$/m³) fora de ±3σ (log) do histórico do SH6',
 $q$WITH p AS (SELECT trade_id, hs6, period, ln(value_usd_fob / qty_m3) lp FROM dw.fact_trade
               WHERE is_current AND qty_m3 > 1 AND value_usd_fob > 1000),
         s AS (SELECT hs6, avg(lp) m, stddev_samp(lp) sd FROM p GROUP BY hs6 HAVING count(*) >= 30)
    SELECT count(*), jsonb_agg(jsonb_build_object('trade_id', trade_id, 'hs6', p.hs6, 'period', period)) FILTER (WHERE rn <= 5)
    FROM (SELECT p.*, row_number() OVER () rn FROM p JOIN s USING (hs6) WHERE abs(p.lp - s.m) > 3 * s.sd) p$q$),
('trade.month_gaps', 'trade', 'warn', 'Meses ausentes na série de exportações BR (entre o primeiro e o último mês)',
 $q$WITH r AS (SELECT is_simulated, min(period) a, max(period) b FROM dw.fact_trade
               WHERE is_current AND reporter_iso3 = 'BRA' AND flow = 'X' GROUP BY is_simulated),
         g AS (SELECT r.is_simulated, m.period FROM r JOIN dw.dim_month m ON m.period BETWEEN r.a AND r.b
               WHERE NOT EXISTS (SELECT 1 FROM dw.fact_trade f WHERE f.is_current AND f.reporter_iso3 = 'BRA'
                                 AND f.flow = 'X' AND f.period = m.period AND f.is_simulated = r.is_simulated))
    SELECT count(*), jsonb_agg(period) FROM g$q$),
('trade.mirror_divergence', 'trade', 'warn', 'Exportação BR→país diverge >15% da importação país←BR (espelho Comtrade), por ano',
 $q$WITH br AS (SELECT partner_iso3 iso3, extract(year FROM period)::int yr, sum(value_usd_fob) v
                FROM dw.fact_trade WHERE is_current AND reporter_iso3 = 'BRA' AND flow = 'X' AND source_id = 'comexstat'
                GROUP BY 1,2),
         mi AS (SELECT reporter_iso3 iso3, extract(year FROM period)::int yr, sum(value_usd_fob) v
                FROM dw.fact_trade WHERE is_current AND partner_iso3 = 'BRA' AND flow = 'M' AND source_id = 'comtrade'
                GROUP BY 1,2)
    SELECT count(*), jsonb_agg(jsonb_build_object('iso3', br.iso3, 'yr', br.yr, 'br', br.v, 'mirror', mi.v))
    FROM br JOIN mi USING (iso3, yr) WHERE abs(mi.v / nullif(br.v, 0) - 1) > 0.15$q$),
('series.month_gaps', 'series', 'warn', 'Séries mensais com meses ausentes',
 $q$WITH r AS (SELECT s.indicator_code, s.geo_iso3, s.is_simulated, min(period) a, max(period) b, count(*) n
               FROM dw.fact_series s JOIN dw.dim_indicator i USING (indicator_code)
               WHERE s.is_current AND i.frequency = 'M' GROUP BY 1,2,3)
    SELECT count(*), jsonb_agg(jsonb_build_object('indicator', indicator_code, 'geo', geo_iso3,
             'missing', (extract(year FROM age(b, a)) * 12 + extract(month FROM age(b, a)) + 1 - n)))
    FROM r WHERE (extract(year FROM age(b, a)) * 12 + extract(month FROM age(b, a)) + 1) > n$q$),
('series.stale', 'series', 'warn', 'Série desatualizada: último período mais antigo que periodicidade + defasagem da fonte',
 $q$WITH l AS (SELECT s.indicator_code, s.geo_iso3, max(s.period) lp, i.frequency, coalesce(src.expected_lag_days, 45) lag
               FROM dw.fact_series s JOIN dw.dim_indicator i USING (indicator_code)
               JOIN meta.source src ON src.source_id = s.source_id
               WHERE s.is_current AND NOT s.is_simulated GROUP BY 1,2,4,5)
    SELECT count(*), jsonb_agg(jsonb_build_object('indicator', indicator_code, 'geo', geo_iso3, 'last', lp))
    FROM l WHERE lp + (CASE frequency WHEN 'D' THEN 1 WHEN 'W' THEN 7 WHEN 'M' THEN 31 WHEN 'Q' THEN 92 ELSE 366 END + lag)
                 * interval '1 day' < current_date$q$),
('series.jump', 'series', 'warn', 'Variação mensal acima de 5σ do histórico da série (possível erro de unidade)',
 $q$WITH d AS (SELECT indicator_code, geo_iso3, period,
                      value / nullif(lag(value) OVER (PARTITION BY indicator_code, geo_iso3 ORDER BY period), 0) - 1 AS c
               FROM mart.v_series_monthly),
         s AS (SELECT indicator_code, geo_iso3, avg(c) m, stddev_samp(c) sd FROM d GROUP BY 1,2 HAVING count(c) >= 24)
    SELECT count(*), jsonb_agg(jsonb_build_object('indicator', d.indicator_code, 'period', d.period)) FILTER (WHERE rn <= 5)
    FROM (SELECT d.*, row_number() OVER () rn FROM d JOIN s USING (indicator_code, geo_iso3)
          WHERE abs(d.c - s.m) > 5 * s.sd AND s.sd > 0) d$q$),
('intel.event_evidence', 'intel', 'error', 'Evento geopolítico sem evidência ou com impacto definido sem confiança',
 $q$SELECT count(*), jsonb_agg(event_id) FROM intel.geo_event WHERE length(trim(evidence)) < 10$q$);

-- Visão consolidada de qualidade por fonte (página DATA QUALITY)
CREATE OR REPLACE VIEW dq.v_source_quality AS
WITH t AS (SELECT source_id, is_simulated, min(period) first_period, max(period) last_period,
                  count(DISTINCT period) periods, max(collected_at) last_collected
           FROM dw.fact_trade WHERE is_current GROUP BY 1,2
           UNION ALL
           SELECT source_id, is_simulated, min(period), max(period), count(DISTINCT period), max(collected_at)
           FROM dw.fact_series WHERE is_current GROUP BY 1,2),
lr AS (SELECT DISTINCT ON (source_id) source_id, status, started_at, finished_at, rows_rejected
       FROM meta.etl_run ORDER BY source_id, started_at DESC),
rej AS (SELECT r.source_id, count(*) n FROM dq.rejected_row x JOIN meta.etl_run r USING (run_id) GROUP BY 1)
SELECT s.source_id, s.name, s.source_type, s.periodicity, s.reliability, s.expected_lag_days,
       t.is_simulated, t.first_period, t.last_period, t.periods, t.last_collected,
       lr.status AS last_run_status, lr.finished_at AS last_run_at,
       coalesce(rej.n, 0) AS rejected_rows,
       CASE WHEN t.last_collected IS NULL THEN 'SEM DADOS'
            WHEN t.is_simulated THEN 'SIMULADO'
            ELSE 'INTEGRADO' END AS integration_status
FROM meta.source s
LEFT JOIN t   ON t.source_id = s.source_id
LEFT JOIN lr  ON lr.source_id = s.source_id
LEFT JOIN rej ON rej.source_id = s.source_id;

CREATE OR REPLACE VIEW dq.v_rule_status AS
SELECT DISTINCT ON (r.rule_id) r.rule_id, r.dataset, r.severity, r.description,
       x.checked_at, x.failing, x.passed, x.sample
FROM dq.rule r LEFT JOIN dq.result x ON x.rule_id = r.rule_id
ORDER BY r.rule_id, x.checked_at DESC NULLS LAST;
