-- 0014 — Defasagem esperada por indicador (sobrepõe a da fonte).
-- A mesma fonte (IBGE SIDRA) publica a PIM-PF ~40 dias após o mês e a PEVS ~9 meses após o fim do ano.
-- A regra series.stale mede: fim do último período carregado + defasagem < hoje.
-- Para a PEVS anual isso precisa cobrir o ano seguinte inteiro + a publicação (365 + ~275 dias).
ALTER TABLE dw.dim_indicator ADD COLUMN IF NOT EXISTS expected_lag_days int;
COMMENT ON COLUMN dw.dim_indicator.expected_lag_days IS 'Defasagem esperada (dias) após o fim do último período; NULL = usa meta.source.expected_lag_days';

UPDATE dw.dim_indicator SET expected_lag_days = 640
 WHERE indicator_code IN ('BR_SILV_PINUS_M3','BR_SILV_EUCA_M3','BR_SILV_PINUS_OTHER_M3','BR_SILV_EUCA_OTHER_M3');

UPDATE dq.rule SET check_sql = $q$WITH l AS (SELECT s.indicator_code, s.geo_iso3, max(s.period) lp, i.frequency,
   coalesce(i.expected_lag_days,
            CASE WHEN s.source_id = 'gwmi_calc' THEN (SELECT expected_lag_days FROM meta.source WHERE source_id = 'comexstat')
                 ELSE src.expected_lag_days END, 45) lag
 FROM dw.fact_series s JOIN dw.dim_indicator i USING (indicator_code)
 JOIN meta.source src ON src.source_id = s.source_id
 WHERE s.is_current AND NOT s.is_simulated
   AND NOT (s.source_id = 'gwmi_calc' AND s.geo_iso3 NOT IN ('WLD','EUU','BRA'))
 GROUP BY 1,2,4,5)
 SELECT count(*), jsonb_agg(jsonb_build_object('indicator', indicator_code, 'geo', geo_iso3, 'last', lp))
 FROM l WHERE lp + (CASE frequency WHEN 'D' THEN 1 WHEN 'W' THEN 7 WHEN 'M' THEN 31 WHEN 'Q' THEN 92 ELSE 366 END + lag)
 * interval '1 day' < current_date$q$
WHERE rule_id = 'series.stale';
