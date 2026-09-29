-- =====================================================================
-- CELPLAC GWMI · 0008 · Carga de tabelas auxiliares oficiais e
-- indicadores derivados (fórmulas registradas em dim_indicator.formula)
-- =====================================================================

-- Staging genérico para tabelas de referência (PAIS, NCM, NCM_UNIDADE, URF)
CREATE UNLOGGED TABLE stg.ref (
    run_id bigint NOT NULL,
    kind   text   NOT NULL CHECK (kind IN ('pais','ncm','unidade','urf')),
    c1 text, c2 text, c3 text, c4 text
);

CREATE OR REPLACE FUNCTION dw.apply_comex_reference(p_run bigint)
RETURNS TABLE (kind text, upserted int, unmapped int)
LANGUAGE plpgsql AS $$
DECLARE n int; u int;
BEGIN
    -- PAIS: c1=CO_PAIS, c2=CO_PAIS_ISOA3, c3=NO_PAIS
    INSERT INTO dw.map_country_comex (co_pais, iso3, iso3_source, name_pt, run_id)
    SELECT s.c1::int, c.iso3, s.c2, s.c3, p_run
    FROM stg.ref s LEFT JOIN dw.dim_country c ON c.iso3 = upper(trim(s.c2))
    WHERE s.run_id = p_run AND s.kind = 'pais'
    ON CONFLICT (co_pais) DO UPDATE SET iso3 = EXCLUDED.iso3, iso3_source = EXCLUDED.iso3_source,
                                        name_pt = EXCLUDED.name_pt, run_id = EXCLUDED.run_id;
    GET DIAGNOSTICS n = ROW_COUNT;
    SELECT count(*) INTO u FROM dw.map_country_comex WHERE iso3 IS NULL AND run_id = p_run;
    kind := 'pais'; upserted := n; unmapped := u; RETURN NEXT;

    -- NCM_UNIDADE: c1=CO_UNID, c2=NO_UNID
    INSERT INTO dw.dim_stat_unit (co_unid, name)
    SELECT DISTINCT ON (s.c1::int) s.c1::int, s.c2 FROM stg.ref s WHERE s.run_id = p_run AND s.kind = 'unidade'
    ON CONFLICT (co_unid) DO UPDATE SET name = EXCLUDED.name;
    GET DIAGNOSTICS n = ROW_COUNT;
    kind := 'unidade'; upserted := n; unmapped := 0; RETURN NEXT;

    -- NCM (somente capítulo 44): c1=CO_NCM, c2=CO_UNID, c3=NO_NCM_POR
    INSERT INTO dw.dim_ncm (ncm8, description_pt, stat_unit_code, stat_unit_name, run_id)
    SELECT DISTINCT ON (lpad(s.c1, 8, '0')) lpad(s.c1, 8, '0'), s.c3, nullif(s.c2, '')::int, un.name, p_run
    FROM stg.ref s LEFT JOIN dw.dim_stat_unit un ON un.co_unid = nullif(s.c2, '')::int
    WHERE s.run_id = p_run AND s.kind = 'ncm' AND lpad(s.c1, 8, '0') LIKE '44%'
    ON CONFLICT (ncm8) DO UPDATE SET description_pt = EXCLUDED.description_pt,
        stat_unit_code = EXCLUDED.stat_unit_code, stat_unit_name = EXCLUDED.stat_unit_name, run_id = EXCLUDED.run_id;
    GET DIAGNOSTICS n = ROW_COUNT;
    SELECT count(DISTINCT n2.hs6) INTO u FROM dw.dim_ncm n2
      LEFT JOIN dw.map_hs6_product h ON h.hs6 = n2.hs6
     WHERE h.hs6 IS NULL AND n2.hs4 IN ('4403','4407','4408','4410','4411','4412');
    kind := 'ncm'; upserted := n; unmapped := u; RETURN NEXT;

    -- URF: c1=CO_URF, c2=NO_URF → agrupamento em portos por padrão de nome
    INSERT INTO dw.map_urf_port (co_urf, urf_name, port_code, run_id)
    SELECT s.c1::int, s.c2,
           CASE WHEN upper(s.c2) LIKE '%PARANAGU%' THEN 'BRPNG'
                WHEN upper(s.c2) LIKE '%ITAJA%' THEN 'BRITJ'
                WHEN upper(s.c2) LIKE '%ITAPO%' THEN 'BRIOA'
                WHEN upper(s.c2) LIKE '%FRANCISCO DO SUL%' THEN 'BRSFS'
                WHEN upper(s.c2) LIKE '%RIO GRANDE%' AND upper(s.c2) NOT LIKE '%NORTE%' THEN 'BRRIG'
                WHEN upper(s.c2) LIKE '%SANTOS%' THEN 'BRSSZ'
                WHEN upper(s.c2) LIKE '%URUGUAIANA%' THEN 'BRUGU'
                WHEN upper(s.c2) LIKE '%FOZ DO IGUA%' THEN 'BRFOZ' END,
           p_run
    FROM stg.ref s WHERE s.run_id = p_run AND s.kind = 'urf'
    ON CONFLICT (co_urf) DO UPDATE SET urf_name = EXCLUDED.urf_name,
        port_code = coalesce(dw.map_urf_port.port_code, EXCLUDED.port_code), run_id = EXCLUDED.run_id;
    GET DIAGNOSTICS n = ROW_COUNT;
    kind := 'urf'; upserted := n; unmapped := 0; RETURN NEXT;

    DELETE FROM stg.ref WHERE run_id = p_run;
END $$;

-- ---------------------------------------------------------------------
-- Indicadores derivados → stg.series (o merge versionado vem depois)
--   group 'br_exports'     : EXP_BR_VALUE, EXP_BR_M3 (por parceiro, WLD e EUU), PLYWOOD_FOB_BR
--   group 'market_imports' : IMP_TOTAL_WOOD (importações do mercado, SH 4412, todas as origens)
-- O run recebe is_simulated conforme o modo efetivo dos dados de origem.
-- ---------------------------------------------------------------------
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

        -- agregados: mundo e União Europeia
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

        -- agregado UE = soma dos membros reportantes (inclui comércio intra-UE; ver nota em docs)
        INSERT INTO stg.series (run_id, indicator_code, geo_iso3, period, value, obs_status)
        SELECT p_run, 'IMP_TOTAL_WOOD', 'EUU', f.period, sum(f.value_usd_fob), 'E'
        FROM mart.v_trade_effective f JOIN dw.dim_country c ON c.iso3 = f.reporter_iso3
        WHERE f.flow = 'M' AND left(f.hs6, 4) = '4412' AND f.partner_iso3 = 'WLD' AND c.is_eu
        GROUP BY f.period;
        GET DIAGNOSTICS k = ROW_COUNT; n := n + k;
    ELSE
        RAISE EXCEPTION 'grupo desconhecido: %', p_group;
    END IF;
    UPDATE meta.etl_run SET rows_staged = n WHERE run_id = p_run;
    RETURN n;
END $$;

-- Modo efetivo de cada grupo derivado (true = origem é simulada)
CREATE OR REPLACE FUNCTION mart.derive_group_is_simulated(p_group text)
RETURNS boolean LANGUAGE sql STABLE AS $$
    SELECT CASE p_group
      WHEN 'br_exports' THEN NOT EXISTS (SELECT 1 FROM dw.fact_trade
                                         WHERE is_current AND NOT is_simulated AND reporter_iso3 = 'BRA' AND flow = 'X')
      WHEN 'market_imports' THEN NOT EXISTS (SELECT 1 FROM dw.fact_trade
                                         WHERE is_current AND NOT is_simulated AND flow = 'M' AND reporter_iso3 <> 'BRA')
    END
$$;
