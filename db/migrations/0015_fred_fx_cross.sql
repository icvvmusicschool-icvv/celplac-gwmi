-- 0015 — FRED (construção EUA + câmbio de mercados) e câmbio cruzado MXN/CNY.
-- O PTAX não publica MXN nem CNY. O FRED publica as taxas H.10 do Fed (DEXMXUS, DEXCHUS: moeda por US$).
-- FX_MXN_BRL e FX_CNY_BRL passam a ser INDICADORES calculados (taxa cruzada), não dado de fonte:
--   FX_MXN_BRL = FX_USD_BRL (PTAX fechamento) / FX_USD_MXN (H.10, meio-dia em Nova York), mesmo dia útil.
-- Os horários de referência diferem (BCB ~13h Brasília × Fed meio-dia NY); a nota fica registrada na fórmula.
INSERT INTO dw.dim_indicator (indicator_code, name_pt, unit, frequency, kind, polarity, category, source_id, source_ref, formula, pulse_key, description) VALUES
('US_HOUSING_STARTS_1F', 'EUA — housing starts unifamiliares', 'mil/ano (SAAR)', 'M', 'data', 1, 'construction', 'fred', 'HOUST1F', NULL, NULL,
 'Census/HUD via FRED. Casas unifamiliares concentram o uso de compensado estrutural e OSB'),
('US_BUILDING_PERMITS', 'EUA — licenças de construção', 'mil/ano (SAAR)', 'M', 'data', 1, 'construction', 'fred', 'PERMIT', NULL, NULL,
 'Census/HUD via FRED. Indicador antecedente dos housing starts'),
('FX_USD_MXN', 'Peso mexicano por US$ (Fed H.10)', 'MXN/US$', 'D', 'data', -1, 'fx', 'fred', 'DEXMXUS', NULL, NULL, 'Taxa de meio-dia em Nova York'),
('FX_USD_CNY', 'Yuan por US$ (Fed H.10)', 'CNY/US$', 'D', 'data', -1, 'fx', 'fred', 'DEXCHUS', NULL, NULL, 'Taxa de meio-dia em Nova York')
ON CONFLICT (indicator_code) DO NOTHING;

UPDATE dw.dim_indicator SET kind = 'indicator', source_id = 'gwmi_calc', source_ref = NULL,
       name_pt = 'Peso mexicano em R$ (taxa cruzada)',
       formula = 'FX_USD_BRL (PTAX fechamento) / FX_USD_MXN (Fed H.10) no mesmo dia útil — horários de referência diferentes',
       description = 'O PTAX não publica MXN; taxa cruzada calculada'
 WHERE indicator_code = 'FX_MXN_BRL';
UPDATE dw.dim_indicator SET kind = 'indicator', source_id = 'gwmi_calc', source_ref = NULL,
       name_pt = 'Yuan em R$ (taxa cruzada)',
       formula = 'FX_USD_BRL (PTAX fechamento) / FX_USD_CNY (Fed H.10) no mesmo dia útil — horários de referência diferentes',
       description = 'O PTAX não publica CNY; taxa cruzada calculada'
 WHERE indicator_code = 'FX_CNY_BRL';

-- Grupo derivado 'fx_cross' → stg.series do run; o merge é dw.merge_series(run) como nos demais derivados.
CREATE OR REPLACE FUNCTION mart.derive_fx_cross(p_run bigint) RETURNS int
LANGUAGE sql AS $$
    WITH usd AS (SELECT period, value FROM dw.fact_series WHERE is_current AND NOT is_simulated
                 AND indicator_code = 'FX_USD_BRL' AND geo_iso3 = 'BRA' AND value IS NOT NULL),
         x AS (SELECT indicator_code, period, value FROM dw.fact_series WHERE is_current AND NOT is_simulated
               AND indicator_code IN ('FX_USD_MXN','FX_USD_CNY') AND value > 0),
         ins AS (
            INSERT INTO stg.series (run_id, indicator_code, geo_iso3, period, value, obs_status)
            SELECT p_run, CASE x.indicator_code WHEN 'FX_USD_MXN' THEN 'FX_MXN_BRL' ELSE 'FX_CNY_BRL' END,
                   'BRA', x.period, round(usd.value / x.value, 6), 'A'
            FROM x JOIN usd USING (period)
            RETURNING 1)
    SELECT count(*)::int FROM ins
$$;
