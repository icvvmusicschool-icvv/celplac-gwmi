-- =====================================================================
-- CELPLAC GWMI · 0010 · Janela anterior incompleta ≠ crescimento
-- Com dados reais só a partir de jan/2025, a janela "12m anteriores" fica
-- parcial e a variação sairia inflada. Variação, participação anterior,
-- 'novo mercado' e tendência só são calculados com a janela anterior
-- completa; senão voltam NULL (EVIDÊNCIA INSUFICIENTE) e a coluna
-- prev_window_complete informa o motivo.
-- =====================================================================
DROP FUNCTION IF EXISTS mart.exports_summary(date, int, text);
DROP FUNCTION IF EXISTS mart.export_destinations(date, int, text);
DROP FUNCTION IF EXISTS mart.exports_by_hs6(date, int);

CREATE OR REPLACE FUNCTION mart.exports_summary(p_end date DEFAULT NULL, p_months int DEFAULT 12, p_family text DEFAULT NULL)
RETURNS TABLE (period_start date, period_end date, value_usd numeric, value_usd_prev numeric, value_var numeric,
               net_kg numeric, net_kg_prev numeric, qty_m3 numeric, qty_m3_prev numeric, m3_var numeric,
               price_usd_m3 numeric, price_usd_m3_prev numeric, destinations int, is_simulated boolean, sources text[],
               prev_months_available int, prev_window_complete boolean)
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
           CASE WHEN count(DISTINCT period) FILTER (WHERE prv) = p_months
                THEN mart.safe_ratio(sum(value_usd_fob) FILTER (WHERE cur), sum(value_usd_fob) FILTER (WHERE prv)) END,
           sum(net_kg) FILTER (WHERE cur), sum(net_kg) FILTER (WHERE prv),
           sum(qty_m3) FILTER (WHERE cur), sum(qty_m3) FILTER (WHERE prv),
           CASE WHEN count(DISTINCT period) FILTER (WHERE prv) = p_months
                THEN mart.safe_ratio(sum(qty_m3) FILTER (WHERE cur), sum(qty_m3) FILTER (WHERE prv)) END,
           round(sum(value_usd_fob) FILTER (WHERE cur AND qty_m3 IS NOT NULL) / nullif(sum(qty_m3) FILTER (WHERE cur), 0), 2),
           round(sum(value_usd_fob) FILTER (WHERE prv AND qty_m3 IS NOT NULL) / nullif(sum(qty_m3) FILTER (WHERE prv), 0), 2),
           count(DISTINCT partner_iso3) FILTER (WHERE cur)::int,
           bool_or(is_simulated), array_agg(DISTINCT source_id),
           (count(DISTINCT period) FILTER (WHERE prv))::int,
           count(DISTINCT period) FILTER (WHERE prv) = p_months
    FROM t, w GROUP BY w.cs, w.ce
$$;

CREATE OR REPLACE FUNCTION mart.export_destinations(p_end date DEFAULT NULL, p_months int DEFAULT 12, p_family text DEFAULT NULL)
RETURNS TABLE (rank int, iso3 char(3), name_pt text, region text, lat numeric, lon numeric,
               value_usd numeric, value_usd_prev numeric, value_var numeric,
               share numeric, share_prev numeric, share_delta numeric,
               qty_m3 numeric, net_kg numeric, price_usd_m3 numeric,
               is_new boolean, trend text, is_simulated boolean, prev_window_complete boolean)
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
    tot AS (SELECT sum(v) tv, sum(v0) tv0 FROM t),
    pc AS MATERIALIZED (SELECT count(DISTINCT f.period) = p_months AS ok FROM mart.v_trade_effective f, w
           WHERE f.reporter_iso3 = 'BRA' AND f.flow = 'X' AND f.period BETWEEN w.ps AND w.pe2)
    SELECT (row_number() OVER (ORDER BY t.v DESC NULLS LAST))::int, t.partner_iso3, c.name_pt, c.region, c.lat, c.lon,
           t.v, CASE WHEN pc.ok THEN t.v0 END, CASE WHEN pc.ok THEN mart.safe_ratio(t.v, t.v0) END,
           round(t.v / nullif(tot.tv, 0), 6),
           CASE WHEN pc.ok THEN round(t.v0 / nullif(tot.tv0, 0), 6) END,
           CASE WHEN pc.ok THEN round(t.v / nullif(tot.tv, 0) - t.v0 / nullif(tot.tv0, 0), 6) END,
           t.m3, t.kg, round(t.v / nullif(t.m3, 0), 2),
           -- novo mercado: participação anterior < 0,3% e valor atual ≥ 3× o anterior
           CASE WHEN pc.ok THEN (t.v0 * 3 <= t.v AND coalesce(t.v0 / nullif(tot.tv0, 0), 0) < 0.003) END,
           CASE WHEN pc.ok THEN mart.trend_arrow(t.v / nullif(tot.tv, 0) - t.v0 / nullif(tot.tv0, 0), 0.002) END,
           t.sim, pc.ok
    FROM t CROSS JOIN tot CROSS JOIN pc JOIN dw.dim_country c ON c.iso3 = t.partner_iso3
    WHERE coalesce(t.v, 0) > 0
    ORDER BY t.v DESC
$$;

CREATE OR REPLACE FUNCTION mart.exports_by_hs6(p_end date DEFAULT NULL, p_months int DEFAULT 12)
RETURNS TABLE (hs6 char(6), description_pt text, product_code text, family text,
               value_usd numeric, value_usd_prev numeric, value_var numeric, qty_m3 numeric, is_simulated boolean, prev_window_complete boolean)
LANGUAGE sql STABLE AS $$
    WITH e AS MATERIALIZED (SELECT coalesce(p_end, mart.last_trade_period('BRA','X')) AS pe),
    w AS MATERIALIZED (SELECT (pe - make_interval(months => p_months - 1))::date AS cs, pe AS ce,
                 (pe - make_interval(months => 2*p_months - 1))::date AS ps,
                 (pe - make_interval(months => p_months))::date AS pe2 FROM e),
    pc AS MATERIALIZED (SELECT count(DISTINCT f.period) = p_months AS ok FROM mart.v_trade_effective f, w
           WHERE f.reporter_iso3 = 'BRA' AND f.flow = 'X' AND f.period BETWEEN w.ps AND w.pe2)
    SELECT f.hs6, h.description_pt, f.product_code, f.product_family,
           sum(f.value_usd_fob) FILTER (WHERE f.period BETWEEN w.cs AND w.ce),
           CASE WHEN bool_and(pc.ok) THEN sum(f.value_usd_fob) FILTER (WHERE f.period BETWEEN w.ps AND w.pe2) END,
           CASE WHEN bool_and(pc.ok) THEN mart.safe_ratio(sum(f.value_usd_fob) FILTER (WHERE f.period BETWEEN w.cs AND w.ce),
                           sum(f.value_usd_fob) FILTER (WHERE f.period BETWEEN w.ps AND w.pe2)) END,
           sum(f.qty_m3) FILTER (WHERE f.period BETWEEN w.cs AND w.ce),
           bool_or(f.is_simulated), bool_and(pc.ok)
    FROM mart.v_trade_effective f CROSS JOIN w CROSS JOIN pc
    LEFT JOIN dw.map_hs6_product h ON h.hs6 = f.hs6
    WHERE f.reporter_iso3 = 'BRA' AND f.flow = 'X' AND f.partner_iso3 NOT IN ('WLD','EUU')
      AND f.period BETWEEN w.ps AND w.ce
    GROUP BY f.hs6, h.description_pt, f.product_code, f.product_family
    ORDER BY 5 DESC NULLS LAST
$$;
