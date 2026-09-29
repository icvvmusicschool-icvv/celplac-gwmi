-- 0017 — Regras de qualidade ajustadas depois da 1ª carga real da Comtrade.
-- trade.mirror_divergence comparava a exportação BR de todo o cap. 44 com o espelho só do SH 4412.
-- Agora compara o mesmo SH4, só em anos com os 12 meses do espelho carregados.
-- (Diferença esperada: CIF × FOB, câmbio e defasagem de embarque; o limiar de 15% separa isso de erro.)
UPDATE dq.rule SET check_sql = $q$WITH mi AS (SELECT reporter_iso3 iso3, extract(year FROM period)::int yr, left(hs6, 4) hs4, sum(value_usd_fob) v
 FROM dw.fact_trade WHERE is_current AND NOT is_simulated AND partner_iso3 = 'BRA' AND flow = 'M' AND source_id = 'comtrade'
 GROUP BY 1,2,3 HAVING count(DISTINCT extract(month FROM period)) = 12),
 br AS (SELECT partner_iso3 iso3, extract(year FROM period)::int yr, left(hs6, 4) hs4, sum(value_usd_fob) v
 FROM dw.fact_trade WHERE is_current AND NOT is_simulated AND reporter_iso3 = 'BRA' AND flow = 'X' AND source_id = 'comexstat'
 GROUP BY 1,2,3)
 SELECT count(*), jsonb_agg(jsonb_build_object('iso3', br.iso3, 'yr', br.yr, 'hs4', br.hs4, 'br_fob', br.v, 'mirror_cif', mi.v,
        'ratio', round(mi.v / nullif(br.v, 0), 3)))
 FROM br JOIN mi USING (iso3, yr, hs4) WHERE abs(mi.v / nullif(br.v, 0) - 1) > 0.15$q$,
 description = 'Exportação BR→país diverge >15% da importação país←BR (espelho Comtrade), mesmo SH4, anos com 12 meses no espelho'
WHERE rule_id = 'trade.mirror_divergence';

-- Volume em m³ só é cobrado onde a plataforma o usa (exportações BR, Comex Stat).
-- Os agregados SH4 da Comtrade não têm unidade m³ por construção (densidade NULL de propósito).
UPDATE dq.rule SET check_sql = $q$SELECT count(*), jsonb_agg(DISTINCT hs6) FROM dw.fact_trade
 WHERE is_current AND qty_m3_method = 'unavailable' AND source_id = 'comexstat'$q$,
 description = 'Exportações BR (Comex Stat) sem volume em m³ (sem unidade m³ e sem densidade cadastrada)'
WHERE rule_id = 'trade.m3_unavailable';
