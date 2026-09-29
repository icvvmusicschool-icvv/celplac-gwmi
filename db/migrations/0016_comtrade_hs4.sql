-- 0016 — UN Comtrade no nível SH4 (concorrentes mundiais e importações dos mercados).
-- A carga usa a API pública de pré-visualização da Comtrade (sem chave, até 500 linhas por consulta),
-- filtrada em customsCode=C00, motCode=0, partner2Code=0 (totais). Valores no nível SH4 entram com
-- ncm8 = SH4 + '0000' → hs6 = SH4 + '00', mapeado para produtos "agregado SH4".
-- Densidade NULL de propósito: sem unidade m³ declarada, o volume fica DADO INDISPONÍVEL em vez de estimado.
INSERT INTO dw.dim_product (product_code, family, name_pt, name_en, density_kg_m3, density_note, is_celplac_core) VALUES
('HS4_4412_TOTAL', 'plywood',  'SH 4412 total (compensado, LVL, painéis estratificados) — agregado Comtrade', 'HS 4412 total', NULL, 'agregado SH4: volume indisponível', false),
('HS4_4408_TOTAL', 'veneer',   'SH 4408 total (lâminas) — agregado Comtrade', 'HS 4408 total', NULL, 'agregado SH4: volume indisponível', false),
('HS4_4407_TOTAL', 'sawnwood', 'SH 4407 total (madeira serrada) — agregado Comtrade', 'HS 4407 total', NULL, 'agregado SH4: volume indisponível', false)
ON CONFLICT (product_code) DO NOTHING;

INSERT INTO dw.map_hs6_product (hs6, product_code, description_pt, note) VALUES
('441200', 'HS4_4412_TOTAL', 'SH 4412 — total do capítulo (agregado)', 'Pseudo-SH6 para dados reportados no nível SH4'),
('440800', 'HS4_4408_TOTAL', 'SH 4408 — total (agregado)', 'Pseudo-SH6 para dados reportados no nível SH4'),
('440700', 'HS4_4407_TOTAL', 'SH 4407 — total (agregado)', 'Pseudo-SH6 para dados reportados no nível SH4')
ON CONFLICT (hs6) DO NOTHING;

-- Concorrentes: o ano padrão passa a ser o último ano FECHADO em que a cobertura de reportantes
-- é comparável à do ano anterior (≥ 90%). A Comtrade anual chega aos poucos; comparar um ano com
-- metade dos países reportados contra um ano completo inventaria "quedas".
CREATE OR REPLACE FUNCTION mart.competitors(p_hs4 text DEFAULT '4412', p_year int DEFAULT NULL)
RETURNS TABLE (rank int, iso3 char(3), name_pt text, value_usd numeric, value_usd_prev numeric, growth numeric,
               share numeric, qty_m3 numeric, price_usd_m3 numeric, is_simulated boolean)
LANGUAGE sql STABLE AS $$
    WITH cov AS MATERIALIZED (
            SELECT extract(year FROM period)::int AS yr, count(DISTINCT reporter_iso3) AS n
            FROM mart.v_trade_effective
            WHERE flow = 'X' AND left(hs6, 4) = p_hs4 AND partner_iso3 = 'WLD'
            GROUP BY 1),
         y AS MATERIALIZED (
            SELECT coalesce(p_year,
                   (SELECT max(c.yr) FROM cov c JOIN cov p ON p.yr = c.yr - 1
                     WHERE c.yr < extract(year FROM current_date) AND c.n >= 0.9 * p.n),
                   (SELECT max(yr) FROM cov WHERE yr < extract(year FROM current_date))) AS yr),
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

-- Importações do mercado: o agregado "UE" somava só os membros carregados e parecia o total do bloco.
-- Sem os 27 membros não há total UE; o agregado sai (continua por país).
CREATE OR REPLACE FUNCTION mart.derive_trade_series(p_run bigint, p_group text)
RETURNS int LANGUAGE plpgsql AS $$
DECLARE n int := 0; k int;
BEGIN
    IF p_group = 'br_exports' THEN
        INSERT INTO stg.series (run_id, indicator_code, geo_iso3, period, value)
        SELECT p_run, 'EXP_BR_VALUE', partner_iso3, period, sum(value_usd_fob)
        FROM mart.v_trade_effective
        WHERE reporter_iso3 = 'BRA' AND flow = 'X' AND partner_iso3 NOT IN ('WLD','EUU','XXX')
          AND product_family IN ('plywood','lvl','veneer')
        GROUP BY partner_iso3, period;
        GET DIAGNOSTICS k = ROW_COUNT; n := n + k;

        INSERT INTO stg.series (run_id, indicator_code, geo_iso3, period, value)
        SELECT p_run, 'EXP_BR_M3', partner_iso3, period, sum(qty_m3)
        FROM mart.v_trade_effective
        WHERE reporter_iso3 = 'BRA' AND flow = 'X' AND partner_iso3 NOT IN ('WLD','EUU','XXX')
          AND product_family IN ('plywood','lvl','veneer') AND qty_m3 IS NOT NULL
        GROUP BY partner_iso3, period;
        GET DIAGNOSTICS k = ROW_COUNT; n := n + k;

        INSERT INTO stg.series (run_id, indicator_code, geo_iso3, period, value)
        SELECT p_run, 'EXP_BR_VALUE', g.geo, f.period, sum(f.value_usd_fob)
        FROM mart.v_trade_effective f
        JOIN dw.dim_country c ON c.iso3 = f.partner_iso3
        CROSS JOIN LATERAL (SELECT 'WLD'::char(3) AS geo UNION ALL SELECT 'EUU' WHERE c.is_eu) g
        WHERE f.reporter_iso3 = 'BRA' AND f.flow = 'X' AND NOT c.is_aggregate
          AND f.product_family IN ('plywood','lvl','veneer')
        GROUP BY g.geo, f.period;
        GET DIAGNOSTICS k = ROW_COUNT; n := n + k;

        INSERT INTO stg.series (run_id, indicator_code, geo_iso3, period, value)
        SELECT p_run, 'PLYWOOD_FOB_BR', 'BRA', period, round(sum(value_usd_fob) / nullif(sum(qty_m3), 0), 4)
        FROM mart.v_trade_effective
        WHERE reporter_iso3 = 'BRA' AND flow = 'X' AND partner_iso3 NOT IN ('WLD','EUU')
          AND product_family = 'plywood' AND qty_m3 > 0
        GROUP BY period;
        GET DIAGNOSTICS k = ROW_COUNT; n := n + k;

    ELSIF p_group = 'market_imports' THEN
        INSERT INTO stg.series (run_id, indicator_code, geo_iso3, period, value)
        SELECT p_run, 'IMP_TOTAL_WOOD', reporter_iso3, period,
               sum(value_usd_fob) FILTER (WHERE partner_iso3 = 'WLD')
        FROM mart.v_trade_effective
        WHERE flow = 'M' AND left(hs6, 4) = '4412' AND reporter_iso3 <> 'BRA'
        GROUP BY reporter_iso3, period
        HAVING sum(value_usd_fob) FILTER (WHERE partner_iso3 = 'WLD') IS NOT NULL;
        GET DIAGNOSTICS k = ROW_COUNT; n := n + k;
    ELSE
        RAISE EXCEPTION 'grupo desconhecido: %', p_group;
    END IF;
    UPDATE meta.etl_run SET rows_staged = n WHERE run_id = p_run;
    RETURN n;
END $$;

UPDATE dw.dim_indicator SET description = 'Importações do destino, todas as origens (Comtrade, valor declarado pelo importador; base CIF quando o país não reporta FOB)'
 WHERE indicator_code = 'IMP_TOTAL_WOOD';
