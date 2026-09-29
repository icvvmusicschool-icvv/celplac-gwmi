-- 0021 — Ajustes de qualidade depois da carga das fontes abertas de macro.
-- 1) series.jump testava a razão v/v(t-1) − 1 em todas as séries. Em séries de variação a/a (que cruzam zero)
--    essa razão explode sem que haja erro nenhum (ex.: +0,1% → −0,4% vira −500%). O teste passa a valer só
--    para séries de nível, estritamente positivas (preços, índices, valores, volumes).
UPDATE dq.rule SET check_sql = $q$WITH d AS (SELECT indicator_code, geo_iso3, period, value,
  value / nullif(lag(value) OVER (PARTITION BY indicator_code, geo_iso3 ORDER BY period), 0) - 1 AS c
  FROM mart.v_series_monthly),
 s AS (SELECT indicator_code, geo_iso3, avg(c) m, stddev_samp(c) sd FROM d GROUP BY 1,2
       HAVING count(c) >= 24 AND min(value) > 0)
 SELECT count(*), jsonb_agg(jsonb_build_object('indicator', d.indicator_code, 'geo', d.geo_iso3, 'period', d.period)) FILTER (WHERE rn <= 5)
 FROM (SELECT d.*, row_number() OVER () rn FROM d JOIN s USING (indicator_code, geo_iso3)
       WHERE abs(d.c - s.m) > 5 * s.sd AND s.sd > 0) d$q$,
 description = 'Salto > 5 desvios-padrão na variação mensal (só séries de nível, estritamente positivas; séries a/a ficam de fora)'
WHERE rule_id = 'series.jump';

-- 2) Macro a/a mistura fontes com defasagens diferentes (FRED/BLS ~30 dias, INDEC ~45, Eurostat ~45, NBS ~20).
--    A construção dos EUA (TTLCONS) sai ~60 dias após o mês. 75 dias cobre todas sem esconder série parada
--    (a China, parada em fev/2026, continua sendo apontada).
UPDATE dw.dim_indicator SET expected_lag_days = 75
 WHERE indicator_code IN ('MACRO_IP_YOY', 'MACRO_CONSTRUCTION_YOY');
