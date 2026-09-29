-- =====================================================================
-- CELPLAC GWMI · 0005 · Marts: indicadores calculados consumidos pela API
--
-- Regra de modo (DEMO × real), aplicada por dataset:
--   se existir dado REAL para aquele recorte, o simulado é ignorado;
--   se não existir, o simulado é servido — sempre com is_simulated = true.
-- =====================================================================

CREATE OR REPLACE FUNCTION mart.trend_arrow(p_chg numeric, p_th numeric DEFAULT 0.005)
RETURNS text LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN p_chg IS NULL THEN NULL
                WHEN p_chg >  p_th THEN '↑'
                WHEN p_chg < -p_th THEN '↓'
                ELSE '→' END
$$;

CREATE OR REPLACE FUNCTION mart.safe_ratio(a numeric, b numeric)
RETURNS numeric LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN b IS NULL OR b = 0 OR a IS NULL THEN NULL ELSE a / b - 1 END
$$;

-- ----------------------------- COMÉRCIO -------------------------------
-- Modo por recorte calculado UMA vez (join), não por linha (subconsulta correlacionada)
CREATE INDEX IF NOT EXISTS fact_trade_real_mode_idx ON dw.fact_trade (reporter_iso3, flow)
    WHERE is_current AND NOT is_simulated;

CREATE OR REPLACE VIEW mart.v_trade_effective AS
WITH real_scope AS (
    SELECT DISTINCT reporter_iso3, flow FROM dw.fact_trade WHERE is_current AND NOT is_simulated)
SELECT f.*, h.product_code, p.family AS product_family
FROM dw.fact_trade f
LEFT JOIN real_scope rs ON rs.reporter_iso3 = f.reporter_iso3 AND rs.flow = f.flow
LEFT JOIN dw.map_hs6_product h ON h.hs6 = f.hs6
LEFT JOIN dw.dim_product p     ON p.product_code = h.product_code
WHERE f.is_current
  AND f.is_simulated = (rs.reporter_iso3 IS NULL);

-- Último mês disponível para um reporter/fluxo
CREATE OR REPLACE FUNCTION mart.last_trade_period(p_reporter char(3) DEFAULT 'BRA', p_flow char(1) DEFAULT 'X')
RETURNS date LANGUAGE sql STABLE AS $$
    SELECT max(period) FROM mart.v_trade_effective WHERE reporter_iso3 = p_reporter AND flow = p_flow
$$;

-- Resumo das exportações (janela móvel de p_months vs janela anterior)
CREATE OR REPLACE FUNCTION mart.exports_summary(p_end date DEFAULT NULL, p_months int DEFAULT 12, p_family text DEFAULT NULL)
RETURNS TABLE (period_start date, period_end date, value_usd numeric, value_usd_prev numeric, value_var numeric,
               net_kg numeric, net_kg_prev numeric, qty_m3 numeric, qty_m3_prev numeric, m3_var numeric,
               price_usd_m3 numeric, price_usd_m3_prev numeric, destinations int, is_simulated boolean, sources text[])
LANGUAGE sql STABLE AS $$
    WITH e AS MATERIALIZED (SELECT coalesce(p_end, mart.last_trade_period('BRA','X')) AS pe),
    w AS MATERIALIZED (SELECT (pe - make_interval(months => p_months - 1))::date AS cs, pe AS ce,
                 (pe - make_interval(months => 2*p_months - 1))::date AS ps,
                 (pe - make_interval(months => p_months))::date AS pe2 FROM e),
    t AS (SELECT f.*, (f.period BETWEEN w.cs AND w.ce) AS cur, (f.period BETWEEN w.ps AND w.pe2) AS prv
          FROM mart.v_trade_effective f, w
          WHERE f.reporter_iso3 = 'BRA' AND f.flow = 'X' AND f.partner_iso3 NOT IN ('WLD','EUU')
            AND (p_family IS NULL OR f.product_family = p_family)
            AND f.period BETWEEN w.ps AND w.ce)
    SELECT w.cs, w.ce,
           sum(value_usd_fob) FILTER (WHERE cur), sum(value_usd_fob) FILTER (WHERE prv),
           mart.safe_ratio(sum(value_usd_fob) FILTER (WHERE cur), sum(value_usd_fob) FILTER (WHERE prv)),
           sum(net_kg) FILTER (WHERE cur), sum(net_kg) FILTER (WHERE prv),
           sum(qty_m3) FILTER (WHERE cur), sum(qty_m3) FILTER (WHERE prv),
           mart.safe_ratio(sum(qty_m3) FILTER (WHERE cur), sum(qty_m3) FILTER (WHERE prv)),
           round(sum(value_usd_fob) FILTER (WHERE cur AND qty_m3 IS NOT NULL) / nullif(sum(qty_m3) FILTER (WHERE cur), 0), 2),
           round(sum(value_usd_fob) FILTER (WHERE prv AND qty_m3 IS NOT NULL) / nullif(sum(qty_m3) FILTER (WHERE prv), 0), 2),
           count(DISTINCT partner_iso3) FILTER (WHERE cur)::int,
           bool_or(is_simulated), array_agg(DISTINCT source_id)
    FROM t, w GROUP BY w.cs, w.ce
$$;

-- Destinos — ranking identificado pelos dados (nenhum país pré-fixado)
CREATE OR REPLACE FUNCTION mart.export_destinations(p_end date DEFAULT NULL, p_months int DEFAULT 12, p_family text DEFAULT NULL)
RETURNS TABLE (rank int, iso3 char(3), name_pt text, region text, lat numeric, lon numeric,
               value_usd numeric, value_usd_prev numeric, value_var numeric,
               share numeric, share_prev numeric, share_delta numeric,
               qty_m3 numeric, net_kg numeric, price_usd_m3 numeric,
               is_new boolean, trend text, is_simulated boolean)
LANGUAGE sql STABLE AS $$
    WITH e AS MATERIALIZED (SELECT coalesce(p_end, mart.last_trade_period('BRA','X')) AS pe),
    w AS MATERIALIZED (SELECT (pe - make_interval(months => p_months - 1))::date AS cs, pe AS ce,
                 (pe - make_interval(months => 2*p_months - 1))::date AS ps,
                 (pe - make_interval(months => p_months))::date AS pe2 FROM e),
    t AS (SELECT f.partner_iso3,
                 sum(f.value_usd_fob) FILTER (WHERE f.period BETWEEN w.cs AND w.ce)  AS v,
                 coalesce(sum(f.value_usd_fob) FILTER (WHERE f.period BETWEEN w.ps AND w.pe2), 0) AS v0,
                 sum(f.qty_m3)  FILTER (WHERE f.period BETWEEN w.cs AND w.ce) AS m3,
                 sum(f.net_kg)  FILTER (WHERE f.period BETWEEN w.cs AND w.ce) AS kg,
                 bool_or(f.is_simulated) AS sim
          FROM mart.v_trade_effective f, w
          WHERE f.reporter_iso3 = 'BRA' AND f.flow = 'X' AND f.partner_iso3 NOT IN ('WLD','EUU')
            AND (p_family IS NULL OR f.product_family = p_family)
            AND f.period BETWEEN w.ps AND w.ce
          GROUP BY f.partner_iso3),
    tot AS (SELECT sum(v) tv, sum(v0) tv0 FROM t)
    SELECT (row_number() OVER (ORDER BY t.v DESC NULLS LAST))::int, t.partner_iso3, c.name_pt, c.region, c.lat, c.lon,
           t.v, t.v0, mart.safe_ratio(t.v, t.v0),
           round(t.v / nullif(tot.tv, 0), 6), round(t.v0 / nullif(tot.tv0, 0), 6),
           round(t.v / nullif(tot.tv, 0) - t.v0 / nullif(tot.tv0, 0), 6),
           t.m3, t.kg, round(t.v / nullif(t.m3, 0), 2),
           -- novo mercado: participação anterior < 0,3% e valor atual ≥ 3× o anterior
           (t.v0 * 3 <= t.v AND coalesce(t.v0 / nullif(tot.tv0, 0), 0) < 0.003),
           mart.trend_arrow(t.v / nullif(tot.tv, 0) - t.v0 / nullif(tot.tv0, 0), 0.002),
           t.sim
    FROM t CROSS JOIN tot JOIN dw.dim_country c ON c.iso3 = t.partner_iso3
    WHERE coalesce(t.v, 0) > 0
    ORDER BY t.v DESC
$$;

-- Exportações por SH6/produto
CREATE OR REPLACE FUNCTION mart.exports_by_hs6(p_end date DEFAULT NULL, p_months int DEFAULT 12)
RETURNS TABLE (hs6 char(6), description_pt text, product_code text, family text,
               value_usd numeric, value_usd_prev numeric, value_var numeric, qty_m3 numeric, is_simulated boolean)
LANGUAGE sql STABLE AS $$
    WITH e AS MATERIALIZED (SELECT coalesce(p_end, mart.last_trade_period('BRA','X')) AS pe),
    w AS MATERIALIZED (SELECT (pe - make_interval(months => p_months - 1))::date AS cs, pe AS ce,
                 (pe - make_interval(months => 2*p_months - 1))::date AS ps,
                 (pe - make_interval(months => p_months))::date AS pe2 FROM e)
    SELECT f.hs6, h.description_pt, f.product_code, f.product_family,
           sum(f.value_usd_fob) FILTER (WHERE f.period BETWEEN w.cs AND w.ce),
           sum(f.value_usd_fob) FILTER (WHERE f.period BETWEEN w.ps AND w.pe2),
           mart.safe_ratio(sum(f.value_usd_fob) FILTER (WHERE f.period BETWEEN w.cs AND w.ce),
                           sum(f.value_usd_fob) FILTER (WHERE f.period BETWEEN w.ps AND w.pe2)),
           sum(f.qty_m3) FILTER (WHERE f.period BETWEEN w.cs AND w.ce),
           bool_or(f.is_simulated)
    FROM mart.v_trade_effective f CROSS JOIN w
    LEFT JOIN dw.map_hs6_product h ON h.hs6 = f.hs6
    WHERE f.reporter_iso3 = 'BRA' AND f.flow = 'X' AND f.partner_iso3 NOT IN ('WLD','EUU')
      AND f.period BETWEEN w.ps AND w.ce
    GROUP BY f.hs6, h.description_pt, f.product_code, f.product_family
    ORDER BY 5 DESC NULLS LAST
$$;

-- Fluxo UF → porto → região (Trade Flow / Sankey)
CREATE OR REPLACE FUNCTION mart.export_flows(p_end date DEFAULT NULL, p_months int DEFAULT 12)
RETURNS TABLE (uf char(2), port_name text, region text, value_usd numeric, qty_m3 numeric, is_simulated boolean)
LANGUAGE sql STABLE AS $$
    WITH e AS MATERIALIZED (SELECT coalesce(p_end, mart.last_trade_period('BRA','X')) AS pe)
    SELECT f.uf, coalesce(p.name, u.urf_name, 'URF ' || f.urf_code) AS port_name, c.region,
           sum(f.value_usd_fob), sum(f.qty_m3), bool_or(f.is_simulated)
    FROM mart.v_trade_effective f CROSS JOIN e
    JOIN dw.dim_country c ON c.iso3 = f.partner_iso3
    LEFT JOIN dw.map_urf_port u ON u.co_urf = f.urf_code
    LEFT JOIN dw.dim_port p ON p.port_code = u.port_code
    WHERE f.reporter_iso3 = 'BRA' AND f.flow = 'X' AND f.partner_iso3 NOT IN ('WLD','EUU')
      AND f.period BETWEEN (e.pe - make_interval(months => p_months - 1))::date AND e.pe
    GROUP BY 1,2,3
    ORDER BY 4 DESC
$$;

-- Série mensal de exportações (total, por família e/ou destino)
CREATE OR REPLACE FUNCTION mart.exports_monthly(p_family text DEFAULT NULL, p_partner char(3) DEFAULT NULL,
                                                p_flow char(1) DEFAULT 'X')
RETURNS TABLE (period date, value_usd numeric, qty_m3 numeric, net_kg numeric, is_simulated boolean)
LANGUAGE sql STABLE AS $$
    SELECT f.period, sum(f.value_usd_fob), sum(f.qty_m3), sum(f.net_kg), bool_or(f.is_simulated)
    FROM mart.v_trade_effective f
    WHERE f.reporter_iso3 = 'BRA' AND f.flow = p_flow AND f.partner_iso3 NOT IN ('WLD','EUU')
      AND (p_family IS NULL OR f.product_family = p_family)
      AND (p_partner IS NULL OR f.partner_iso3 = p_partner)
    GROUP BY f.period ORDER BY f.period
$$;

-- Pesquisa NCM (NCM · produto · país · ano · mês)
CREATE OR REPLACE FUNCTION mart.ncm_search(p_q text DEFAULT NULL, p_family text DEFAULT NULL, p_partner char(3) DEFAULT NULL,
                                           p_year int DEFAULT NULL, p_month int DEFAULT NULL, p_flow char(1) DEFAULT 'X')
RETURNS TABLE (ncm8 char(8), hs6 char(6), description_pt text, family text, value_usd numeric, net_kg numeric,
               qty_m3 numeric, price_usd_m3 numeric, months int, is_simulated boolean)
LANGUAGE sql STABLE AS $$
    SELECT f.ncm8, f.hs6, coalesce(n.description_pt, h.description_pt), f.product_family,
           sum(f.value_usd_fob), sum(f.net_kg), sum(f.qty_m3),
           round(sum(f.value_usd_fob) / nullif(sum(f.qty_m3), 0), 2),
           count(DISTINCT f.period)::int, bool_or(f.is_simulated)
    FROM mart.v_trade_effective f
    LEFT JOIN dw.dim_ncm n ON n.ncm8 = f.ncm8
    LEFT JOIN dw.map_hs6_product h ON h.hs6 = f.hs6
    WHERE f.reporter_iso3 = 'BRA' AND f.flow = p_flow AND f.partner_iso3 NOT IN ('WLD','EUU')
      AND (p_q IS NULL OR f.ncm8 LIKE replace(p_q, '.', '') || '%'
           OR coalesce(n.description_pt, h.description_pt) ILIKE '%' || p_q || '%')
      AND (p_family  IS NULL OR f.product_family = p_family)
      AND (p_partner IS NULL OR f.partner_iso3 = p_partner)
      AND (p_year  IS NULL OR extract(year  FROM f.period) = p_year)
      AND (p_month IS NULL OR extract(month FROM f.period) = p_month)
    GROUP BY 1,2,3,4
    ORDER BY 5 DESC NULLS LAST
$$;

-- Concorrentes: exportadores mundiais por SH4, identificados pelos dados.
-- Total do reporter = linha parceiro 'WLD' (Comtrade) quando existir; senão soma dos parceiros.
CREATE OR REPLACE FUNCTION mart.competitors(p_hs4 text DEFAULT '4412', p_year int DEFAULT NULL)
RETURNS TABLE (rank int, iso3 char(3), name_pt text, value_usd numeric, value_usd_prev numeric, growth numeric,
               share numeric, qty_m3 numeric, price_usd_m3 numeric, is_simulated boolean)
LANGUAGE sql STABLE AS $$
    -- padrão: último ano COMPLETO (12 meses) para não comparar ano parcial com ano cheio
    WITH y AS MATERIALIZED (SELECT coalesce(p_year, (SELECT max(z.yr) FROM (
                   SELECT extract(year FROM period)::int AS yr FROM mart.v_trade_effective
                   WHERE flow = 'X' AND left(hs6, 4) = p_hs4 GROUP BY 1
                   HAVING count(DISTINCT extract(month FROM period)) = 12) z)) AS yr),
    b AS (SELECT f.reporter_iso3, extract(year FROM f.period)::int AS yr, (f.partner_iso3 = 'WLD') AS is_wld,
                 sum(f.value_usd_fob) AS v, sum(f.qty_m3) AS m3, bool_or(f.is_simulated) AS sim
          FROM mart.v_trade_effective f CROSS JOIN y
          WHERE f.flow = 'X' AND left(f.hs6, 4) = p_hs4 AND f.partner_iso3 <> 'EUU'
            AND extract(year FROM f.period) IN (y.yr, y.yr - 1)
          GROUP BY 1,2,3),
    r AS (SELECT DISTINCT ON (reporter_iso3, yr) reporter_iso3, yr, v, m3, sim
          FROM b ORDER BY reporter_iso3, yr, is_wld DESC),
    t AS (SELECT r.reporter_iso3,
                 max(r.v)  FILTER (WHERE r.yr = y.yr) AS v, max(r.v) FILTER (WHERE r.yr = y.yr - 1) AS v0,
                 max(r.m3) FILTER (WHERE r.yr = y.yr) AS m3, bool_or(r.sim) AS sim
          FROM r CROSS JOIN y GROUP BY r.reporter_iso3)
    SELECT (row_number() OVER (ORDER BY t.v DESC NULLS LAST))::int, t.reporter_iso3, c.name_pt, t.v, t.v0,
           mart.safe_ratio(t.v, t.v0), round(t.v / nullif(sum(t.v) OVER (), 0), 6), t.m3,
           round(t.v / nullif(t.m3, 0), 2), t.sim
    FROM t JOIN dw.dim_country c ON c.iso3 = t.reporter_iso3
    WHERE t.v > 0 ORDER BY t.v DESC
$$;

-- ------------------------------ SÉRIES --------------------------------
CREATE INDEX IF NOT EXISTS fact_series_real_mode_idx ON dw.fact_series (indicator_code, geo_iso3)
    WHERE is_current AND NOT is_simulated;

CREATE OR REPLACE VIEW mart.v_series_effective AS
WITH real_scope AS (
    SELECT DISTINCT indicator_code, geo_iso3 FROM dw.fact_series WHERE is_current AND NOT is_simulated)
SELECT f.*
FROM dw.fact_series f
LEFT JOIN real_scope rs ON rs.indicator_code = f.indicator_code AND rs.geo_iso3 = f.geo_iso3
WHERE f.is_current
  AND f.is_simulated = (rs.indicator_code IS NULL);

-- Mensaliza séries diárias/semanais (média do mês); mensais passam direto
CREATE OR REPLACE VIEW mart.v_series_monthly AS
SELECT s.indicator_code, s.geo_iso3, date_trunc('month', s.period)::date AS period,
       avg(s.value) AS value, count(s.value)::int AS n_obs,
       bool_or(s.is_simulated) AS is_simulated, min(s.source_id) AS source_id,
       max(s.collected_at) AS collected_at, max(s.run_id) AS run_id
FROM mart.v_series_effective s
JOIN dw.dim_indicator i ON i.indicator_code = s.indicator_code
WHERE i.frequency IN ('D','W','M')
GROUP BY 1,2,3;

-- Último valor + variações + média 5 anos — alimenta Market Pulse e KPIs
CREATE OR REPLACE VIEW mart.v_series_latest AS
WITH m AS (
    SELECT *, row_number() OVER (PARTITION BY indicator_code, geo_iso3 ORDER BY period DESC) AS rn
    FROM mart.v_series_monthly WHERE value IS NOT NULL),
a AS (SELECT indicator_code, geo_iso3, avg(value) AS avg60, stddev_samp(value) AS sd60
      FROM m WHERE rn <= 60 GROUP BY 1,2)
SELECT l.indicator_code, l.geo_iso3, i.name_pt, i.unit, i.category, i.polarity, i.pulse_key, i.kind,
       l.period, l.value, p.period AS prev_period, p.value AS prev_value,
       mart.safe_ratio(l.value, p.value) AS chg_mom,
       y.value AS yoy_base, mart.safe_ratio(l.value, y.value) AS chg_yoy,
       a.avg60, mart.safe_ratio(l.value, a.avg60) AS vs_avg60,
       s6.value AS value_6m_ago, mart.safe_ratio(l.value, s6.value) AS mom_6m,
       mart.trend_arrow(mart.safe_ratio(l.value, p.value)) AS trend,
       l.source_id, l.collected_at, l.run_id, l.is_simulated
FROM m l
JOIN dw.dim_indicator i ON i.indicator_code = l.indicator_code
LEFT JOIN m p  ON p.indicator_code = l.indicator_code AND p.geo_iso3 = l.geo_iso3 AND p.rn = 2
LEFT JOIN m y  ON y.indicator_code = l.indicator_code AND y.geo_iso3 = l.geo_iso3
              AND y.period = (l.period - interval '12 months')::date
LEFT JOIN m s6 ON s6.indicator_code = l.indicator_code AND s6.geo_iso3 = l.geo_iso3
              AND s6.period = (l.period - interval '6 months')::date
LEFT JOIN a    ON a.indicator_code = l.indicator_code AND a.geo_iso3 = l.geo_iso3
WHERE l.rn = 1;

-- Ciclo de mercado por regra configurável (nível vs média 5a × momentum 6m)
CREATE OR REPLACE FUNCTION mart.market_cycle(p_mom_th numeric DEFAULT NULL)
RETURNS TABLE (indicator_code text, geo_iso3 char(3), label text, level_vs_avg numeric, momentum_6m numeric,
               phase text, period date, is_simulated boolean)
LANGUAGE sql STABLE AS $$
    WITH th AS (SELECT coalesce(p_mom_th,
                   (SELECT (value->>'momentum_threshold')::numeric FROM meta.setting WHERE key = 'cycle'), 0.01) AS t)
    SELECT l.indicator_code, l.geo_iso3, coalesce(l.pulse_key, l.name_pt), l.vs_avg60, l.mom_6m,
           CASE WHEN l.vs_avg60 IS NULL OR l.mom_6m IS NULL THEN 'EVIDÊNCIA INSUFICIENTE'
                WHEN l.vs_avg60 >= 0 AND l.mom_6m >  th.t THEN 'EXPANSÃO'
                WHEN l.vs_avg60 >= 0 AND l.mom_6m < -th.t THEN 'DESACELERAÇÃO'
                WHEN l.vs_avg60 >= 0 THEN 'PICO'
                WHEN l.mom_6m > th.t THEN 'RECUPERAÇÃO'
                ELSE 'CONTRAÇÃO' END,
           l.period, l.is_simulated
    FROM mart.v_series_latest l CROSS JOIN th
    WHERE l.indicator_code IN (SELECT jsonb_array_elements_text(value->'indicators')
                                 FROM meta.setting WHERE key = 'cycle')
$$;

-- Câmbio: estatísticas (volatilidade anualizada de retornos mensais em log, 12m)
CREATE OR REPLACE VIEW mart.v_fx_stats AS
WITH m AS (
    SELECT indicator_code, period, value,
           ln(value / lag(value) OVER (PARTITION BY indicator_code ORDER BY period)) AS lr,
           row_number() OVER (PARTITION BY indicator_code ORDER BY period DESC) AS rn
    FROM mart.v_series_monthly
    WHERE indicator_code LIKE 'FX\_%' AND geo_iso3 = 'BRA' AND value > 0)
SELECT l.*, v.vol_12m
FROM mart.v_series_latest l
JOIN (SELECT indicator_code, stddev_samp(lr) * sqrt(12) AS vol_12m FROM m WHERE rn <= 12 GROUP BY 1) v
  ON v.indicator_code = l.indicator_code
WHERE l.geo_iso3 = 'BRA';
