-- 0012 — Regras de qualidade para séries derivadas por parceiro (vinda da 1ª carga real de séries).
-- EXP_BR_VALUE / EXP_BR_M3 por país vêm de dw.fact_trade: mês sem linha no Comex Stat = sem embarque
-- registrado, não observação faltante. Essas séries não entram em "meses ausentes" nem em "série
-- desatualizada"; os agregados (WLD, EUU, BRA) continuam checados. Para séries derivadas (gwmi_calc),
-- a defasagem esperada é a da fonte de origem (Comex Stat), não zero.
UPDATE dq.rule SET check_sql = $q$WITH r AS (SELECT s.indicator_code, s.geo_iso3, s.is_simulated, min(period) a, max(period) b, count(*) n
 FROM dw.fact_series s JOIN dw.dim_indicator i USING (indicator_code)
 WHERE s.is_current AND i.frequency = 'M'
   AND NOT (s.source_id = 'gwmi_calc' AND s.geo_iso3 NOT IN ('WLD','EUU','BRA'))
 GROUP BY 1,2,3)
 SELECT count(*), jsonb_agg(jsonb_build_object('indicator', indicator_code, 'geo', geo_iso3,
 'missing', (extract(year FROM age(b, a)) * 12 + extract(month FROM age(b, a)) + 1 - n)))
 FROM r WHERE (extract(year FROM age(b, a)) * 12 + extract(month FROM age(b, a)) + 1) > n$q$,
 description = 'Séries mensais com meses ausentes (exceto derivadas por parceiro: mês sem embarque não é lacuna)'
WHERE rule_id = 'series.month_gaps';

UPDATE dq.rule SET check_sql = $q$WITH l AS (SELECT s.indicator_code, s.geo_iso3, max(s.period) lp, i.frequency,
   coalesce(CASE WHEN s.source_id = 'gwmi_calc' THEN (SELECT expected_lag_days FROM meta.source WHERE source_id = 'comexstat')
                 ELSE src.expected_lag_days END, 45) lag
 FROM dw.fact_series s JOIN dw.dim_indicator i USING (indicator_code)
 JOIN meta.source src ON src.source_id = s.source_id
 WHERE s.is_current AND NOT s.is_simulated
   AND NOT (s.source_id = 'gwmi_calc' AND s.geo_iso3 NOT IN ('WLD','EUU','BRA'))
 GROUP BY 1,2,4,5)
 SELECT count(*), jsonb_agg(jsonb_build_object('indicator', indicator_code, 'geo', geo_iso3, 'last', lp))
 FROM l WHERE lp + (CASE frequency WHEN 'D' THEN 1 WHEN 'W' THEN 7 WHEN 'M' THEN 31 WHEN 'Q' THEN 92 ELSE 366 END + lag)
 * interval '1 day' < current_date$q$,
 description = 'Série desatualizada: último período mais antigo que periodicidade + defasagem da fonte (derivadas: defasagem do Comex Stat)'
WHERE rule_id = 'series.stale';

-- PTAX não publica CNY nem MXN (serviço Moedas do Olinda, set/2026: AUD CAD CHF DKK EUR GBP JPY NOK SEK USD).
UPDATE dw.dim_indicator SET description = 'DADO INDISPONÍVEL no PTAX (o serviço não publica CNY). Fonte alternativa a definir.'
WHERE indicator_code = 'FX_CNY_BRL';
UPDATE dw.dim_indicator SET description = 'DADO INDISPONÍVEL no PTAX (o serviço não publica MXN). Fonte alternativa a definir.'
WHERE indicator_code = 'FX_MXN_BRL';
