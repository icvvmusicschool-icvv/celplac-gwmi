-- =====================================================================
-- CELPLAC GWMI · 0009 · Ajustes revelados pela 1ª carga real (Comex 2025–2026)
--  1) Países: todo país da tabela oficial PAIS entra em dim_country, com
--     região vinda de PAIS_BLOCO (bloco continental). Antes, 178 países
--     caíam em 'XXX' e linhas distintas eram somadas.
--  2) SH6 do recorte sem produto associado (teca, OSB, HDF, serrados
--     'outros', blockboard, 4412.9x…) passam a ter produto.
--  3) Semântica de snapshot: o arquivo anual do Comex é a verdade do ano;
--     linhas que sumiram do arquivo são aposentadas (não apagadas).
-- =====================================================================

-- ---------- 1) países ----------
ALTER TABLE stg.ref DROP CONSTRAINT IF EXISTS ref_kind_check;
ALTER TABLE stg.ref ADD CONSTRAINT ref_kind_check CHECK (kind IN ('pais','ncm','unidade','urf','bloco'));
ALTER TABLE dw.dim_country ADD COLUMN IF NOT EXISTS origin text NOT NULL DEFAULT 'curado'
    CHECK (origin IN ('curado','comex_pais'));

CREATE OR REPLACE FUNCTION dw.region_from_bloco(p text) RETURNS text LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE p WHEN 'América do Norte' THEN 'América do Norte'
                  WHEN 'América Central e Caribe' THEN 'América Central e Caribe'
                  WHEN 'América do Sul' THEN 'América do Sul'
                  WHEN 'Europa' THEN 'Europa'
                  WHEN 'Ásia (Exclusive Oriente Médio)' THEN 'Ásia'
                  WHEN 'Oriente Médio' THEN 'Oriente Médio'
                  WHEN 'África' THEN 'África'
                  WHEN 'Oceania' THEN 'Oceania' END
$$;

CREATE OR REPLACE FUNCTION dw.apply_comex_reference(p_run bigint)
RETURNS TABLE (kind text, upserted int, unmapped int)
LANGUAGE plpgsql AS $$
DECLARE n int; u int;
BEGIN
    -- PAIS + PAIS_BLOCO: cria países ausentes (curadoria manual nunca é sobrescrita)
    INSERT INTO dw.dim_country (iso3, name_pt, region, origin)
    SELECT DISTINCT ON (upper(trim(p.c2))) upper(trim(p.c2)), p.c3,
           coalesce((SELECT dw.region_from_bloco(b.c2) FROM stg.ref b
                      WHERE b.run_id = p_run AND b.kind = 'bloco' AND b.c1::int = p.c1::int
                        AND dw.region_from_bloco(b.c2) IS NOT NULL LIMIT 1), 'Não classificada'),
           'comex_pais'
    FROM stg.ref p
    WHERE p.run_id = p_run AND p.kind = 'pais' AND upper(trim(p.c2)) ~ '^[A-Z]{3}$'
      AND upper(trim(p.c2)) NOT IN ('ZZZ')
    ON CONFLICT (iso3) DO NOTHING;
    GET DIAGNOSTICS n = ROW_COUNT;
    kind := 'pais_novos'; upserted := n; unmapped := 0; RETURN NEXT;

    INSERT INTO dw.map_country_comex (co_pais, iso3, iso3_source, name_pt, run_id)
    SELECT s.c1::int, c.iso3, s.c2, s.c3, p_run
    FROM stg.ref s LEFT JOIN dw.dim_country c ON c.iso3 = upper(trim(s.c2))
    WHERE s.run_id = p_run AND s.kind = 'pais'
    ON CONFLICT (co_pais) DO UPDATE SET iso3 = EXCLUDED.iso3, iso3_source = EXCLUDED.iso3_source,
                                        name_pt = EXCLUDED.name_pt, run_id = EXCLUDED.run_id;
    GET DIAGNOSTICS n = ROW_COUNT;
    SELECT count(*) INTO u FROM dw.map_country_comex WHERE iso3 IS NULL AND run_id = p_run;
    kind := 'pais'; upserted := n; unmapped := u; RETURN NEXT;

    INSERT INTO dw.dim_stat_unit (co_unid, name)
    SELECT DISTINCT ON (s.c1::int) s.c1::int, s.c2 FROM stg.ref s WHERE s.run_id = p_run AND s.kind = 'unidade'
    ON CONFLICT (co_unid) DO UPDATE SET name = EXCLUDED.name;
    GET DIAGNOSTICS n = ROW_COUNT;
    kind := 'unidade'; upserted := n; unmapped := 0; RETURN NEXT;

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

-- ---------- 2) produtos e SH6 ----------
INSERT INTO dw.dim_product (product_code, family, name_pt, name_en, density_kg_m3, density_note, is_celplac_core) VALUES
('ROUNDWOOD_TROPICAL','roundwood','Madeira em tora — tropical (inclui teca)','Tropical logs',900,'validar',false),
('ROUNDWOOD_OTHER','roundwood','Madeira em tora — outras não coníferas','Other non-coniferous logs',950,'validar',false),
('ROUNDWOOD_CONIFER_OTHER','roundwood','Madeira em tora — outras coníferas','Other coniferous logs',800,'validar',false),
('SAWN_CONIFER_OTHER','sawnwood','Madeira serrada — outras coníferas','Other coniferous sawnwood',480,'validar',false),
('SAWN_OTHER','sawnwood','Madeira serrada — outras não coníferas (ex.: eucalipto)','Other non-coniferous sawnwood',700,'validar',false),
('OSB','panels','OSB','Oriented strand board',620,'validar',false),
('FIBREBOARD_OTHER','panels','Outros painéis de fibras (HDF e outros)','Other fibreboard',850,'validar',false),
('BLOCKBOARD','plywood','Blockboard / laminboard / battenboard','Blockboard',520,'validar',true),
('PLYWOOD_OTHER','plywood','Outras madeiras compensadas/estratificadas (4412.9x)','Other plywood/laminated wood',560,'validar',true)
ON CONFLICT (product_code) DO NOTHING;

INSERT INTO dw.map_hs6_product (hs6, product_code, description_pt, note) VALUES
('440312','ROUNDWOOD_OTHER','Madeira em bruto tratada — não coníferas',NULL),
('440324','ROUNDWOOD_CONIFER_OTHER','Madeira em bruto — abeto/espruce, outras',NULL),
('440342','ROUNDWOOD_TROPICAL','Madeira em bruto — teca',NULL),
('440349','ROUNDWOOD_TROPICAL','Madeira em bruto — outras tropicais',NULL),
('440399','ROUNDWOOD_OTHER','Madeira em bruto — outras',NULL),
('440713','SAWN_CONIFER_OTHER','Madeira serrada — S-P-F (espruce, pinus, abeto)',NULL),
('440719','SAWN_CONIFER_OTHER','Madeira serrada — outras coníferas',NULL),
('440721','SAWN_TROPICAL','Madeira serrada — mogno',NULL),
('440722','SAWN_TROPICAL','Madeira serrada — virola, imbuia e balsa',NULL),
('440723','SAWN_TROPICAL','Madeira serrada — teca',NULL),
('440793','SAWN_OTHER','Madeira serrada — bordo (maple)',NULL),
('440799','SAWN_OTHER','Madeira serrada — outras',NULL),
('441012','OSB','Painéis de partículas orientadas (OSB)',NULL),
('441019','PARTICLEBOARD','Painéis de partículas — outros',NULL),
('441090','PARTICLEBOARD','Painéis de outras matérias lenhosas',NULL),
('441192','FIBREBOARD_OTHER','Painéis de fibras — densidade > 0,8 g/cm³',NULL),
('441193','FIBREBOARD_OTHER','Painéis de fibras — densidade > 0,5 e ≤ 0,8 g/cm³',NULL),
('441194','FIBREBOARD_OTHER','Painéis de fibras — densidade ≤ 0,5 g/cm³',NULL),
('441251','BLOCKBOARD','Blockboard/laminboard — ao menos uma face tropical',NULL),
('441252','BLOCKBOARD','Blockboard/laminboard — outro, face não conífera',NULL),
('441259','BLOCKBOARD','Blockboard/laminboard — outros',NULL),
('441291','PLYWOOD_OTHER','Outras madeiras compensadas — ao menos uma face tropical',NULL),
('441292','PLYWOOD_OTHER','Outras madeiras compensadas — ao menos uma face não conífera',NULL),
('441299','PLYWOOD_OTHER','Outras madeiras compensadas — outras',NULL)
ON CONFLICT (hs6) DO NOTHING;

-- descrições oficiais (NCM.csv) prevalecem quando disponíveis
UPDATE dw.map_hs6_product h SET description_pt = n.description_pt
FROM (SELECT DISTINCT ON (hs6) hs6, description_pt FROM dw.dim_ncm ORDER BY hs6, ncm8) n
WHERE n.hs6 = h.hs6 AND n.description_pt IS NOT NULL;

-- ---------- 3) merge com snapshot ----------
ALTER TABLE meta.etl_run ADD COLUMN IF NOT EXISTS rows_retired int DEFAULT 0;
DROP FUNCTION IF EXISTS dw.merge_trade(bigint);

CREATE OR REPLACE FUNCTION dw.merge_trade(p_run bigint, p_snapshot_from date DEFAULT NULL, p_snapshot_to date DEFAULT NULL)
RETURNS TABLE (inserted int, revised int, unchanged int, unmapped int, retired int)
LANGUAGE plpgsql AS $$
DECLARE
    v_sim boolean; v_src text;
    v_ins int := 0; v_rev int := 0; v_unc int := 0; v_unm int := 0; v_ret int := 0;
BEGIN
    SELECT r.is_simulated, r.source_id INTO v_sim, v_src FROM meta.etl_run r WHERE r.run_id = p_run;
    IF v_src IS NULL THEN RAISE EXCEPTION 'run % inexistente', p_run; END IF;

    DROP TABLE IF EXISTS _mt_s;
    CREATE TEMP TABLE _mt_s ON COMMIT DROP AS
    SELECT s.flow, s.period,
           CASE s.code_scheme WHEN 'iso3' THEN s.reporter_code::char(3)
                ELSE coalesce((SELECT m.iso3 FROM dw.map_country_comex m WHERE m.co_pais::text = s.reporter_code),
                              CASE WHEN s.reporter_code = 'BRA' THEN 'BRA' END, 'XXX') END::char(3) AS reporter_iso3,
           CASE s.code_scheme WHEN 'iso3' THEN
                     CASE WHEN EXISTS (SELECT 1 FROM dw.dim_country c WHERE c.iso3 = s.partner_code) THEN s.partner_code ELSE 'XXX' END
                ELSE coalesce((SELECT m.iso3 FROM dw.map_country_comex m WHERE m.co_pais::text = s.partner_code), 'XXX') END::char(3) AS partner_iso3,
           s.ncm8, s.uf, s.urf_code, s.via_code,
           sum(s.value_usd_fob) AS v, sum(s.value_freight_usd) AS fr, sum(s.value_insurance_usd) AS ins,
           sum(s.net_kg) AS kg, sum(s.qty_stat) AS q, max(s.stat_unit_code) AS su
    FROM stg.trade s WHERE s.run_id = p_run
    GROUP BY 1,2,3,4,5,6,7,8;

    SELECT count(*) INTO v_unm FROM _mt_s WHERE partner_iso3 = 'XXX' OR reporter_iso3 = 'XXX';
    IF v_unm > 0 THEN
        INSERT INTO dq.rejected_row (run_id, dataset, reason, row_data)
        SELECT p_run, 'trade', 'país não mapeado → XXX (linha mantida)', to_jsonb(x)
        FROM (SELECT * FROM _mt_s WHERE partner_iso3 = 'XXX' OR reporter_iso3 = 'XXX' LIMIT 200) x;
    END IF;

    DROP TABLE IF EXISTS _mt_c;
    CREATE TEMP TABLE _mt_c ON COMMIT DROP AS
    SELECT s.*, f.trade_id, f.version AS old_version,
           CASE WHEN f.trade_id IS NULL THEN 'new'
                WHEN f.value_usd_fob IS DISTINCT FROM s.v OR f.net_kg IS DISTINCT FROM s.kg
                  OR f.qty_stat IS DISTINCT FROM s.q THEN 'revised'
                ELSE 'same' END AS st
    FROM _mt_s s
    LEFT JOIN dw.fact_trade f
      ON f.is_current AND f.is_simulated = v_sim AND f.source_id = v_src
     AND f.flow = s.flow AND f.period = s.period AND f.reporter_iso3 = s.reporter_iso3
     AND f.partner_iso3 = s.partner_iso3 AND f.ncm8 = s.ncm8 AND f.uf = s.uf
     AND f.urf_code = s.urf_code AND f.via_code = s.via_code;

    -- snapshot: linhas vigentes do escopo que não vieram no arquivo são aposentadas
    IF p_snapshot_from IS NOT NULL THEN
        UPDATE dw.fact_trade f SET is_current = false, superseded_at = now(), superseded_by_run = p_run
        WHERE f.is_current AND f.is_simulated = v_sim AND f.source_id = v_src
          AND f.period BETWEEN p_snapshot_from AND p_snapshot_to
          AND (f.flow, f.reporter_iso3) IN (SELECT DISTINCT flow, reporter_iso3 FROM _mt_s)
          AND NOT EXISTS (SELECT 1 FROM _mt_s s
                          WHERE s.flow = f.flow AND s.period = f.period AND s.reporter_iso3 = f.reporter_iso3
                            AND s.partner_iso3 = f.partner_iso3 AND s.ncm8 = f.ncm8 AND s.uf = f.uf
                            AND s.urf_code = f.urf_code AND s.via_code = f.via_code);
        GET DIAGNOSTICS v_ret = ROW_COUNT;
    END IF;

    UPDATE dw.fact_trade f SET is_current = false, superseded_at = now(), superseded_by_run = p_run
    FROM _mt_c c WHERE c.st = 'revised' AND f.trade_id = c.trade_id;

    INSERT INTO dw.fact_trade (flow, period, reporter_iso3, partner_iso3, ncm8, uf, urf_code, via_code,
        value_usd_fob, value_freight_usd, value_insurance_usd, net_kg, qty_stat, stat_unit_code,
        qty_m3, qty_m3_method, source_id, run_id, version, is_simulated)
    SELECT c.flow, c.period, c.reporter_iso3, c.partner_iso3, c.ncm8, c.uf, c.urf_code, c.via_code,
           c.v, c.fr, c.ins, c.kg, c.q, c.su,
           CASE WHEN u.is_m3 THEN c.q
                WHEN p.density_kg_m3 IS NOT NULL AND c.kg IS NOT NULL THEN round(c.kg / p.density_kg_m3, 3) END,
           CASE WHEN u.is_m3 THEN 'stat_unit'
                WHEN p.density_kg_m3 IS NOT NULL AND c.kg IS NOT NULL THEN 'density'
                ELSE 'unavailable' END,
           v_src, p_run, coalesce(c.old_version, 0) + 1, v_sim
    FROM _mt_c c
    LEFT JOIN dw.dim_stat_unit u ON u.co_unid = c.su
    LEFT JOIN dw.map_hs6_product h ON h.hs6 = left(c.ncm8, 6)
    LEFT JOIN dw.dim_product p ON p.product_code = h.product_code
    WHERE c.st IN ('new','revised');

    SELECT count(*) FILTER (WHERE st = 'new'), count(*) FILTER (WHERE st = 'revised'),
           count(*) FILTER (WHERE st = 'same')
      INTO v_ins, v_rev, v_unc FROM _mt_c;

    DELETE FROM stg.trade WHERE run_id = p_run;
    UPDATE meta.etl_run SET rows_inserted = v_ins, rows_revised = v_rev, rows_unchanged = v_unc, rows_retired = v_ret
     WHERE run_id = p_run;
    RETURN QUERY SELECT v_ins, v_rev, v_unc, v_unm, v_ret;
END $$;
