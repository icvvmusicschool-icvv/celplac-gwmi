-- =====================================================================
-- CELPLAC GWMI · 0003 · Fatos versionados (histórico de revisões) + staging
--
-- Histórico: fontes oficiais revisam números (Comex Stat, Comtrade, FAO).
-- Nunca sobrescrevemos: a linha antiga vira is_current=false e a nova
-- entra com version+1, apontando para o run que a trouxe.
-- is_simulated separa fisicamente dado DEMO de dado real na mesma tabela.
-- =====================================================================

-- ------------------------------ COMÉRCIO ------------------------------
CREATE TABLE dw.fact_trade (
    trade_id        bigserial PRIMARY KEY,
    flow            char(1)  NOT NULL CHECK (flow IN ('X','M')),     -- X=exportação M=importação (do ponto de vista do reporter)
    period          date     NOT NULL REFERENCES dw.dim_month(period),
    reporter_iso3   char(3)  NOT NULL REFERENCES dw.dim_country(iso3),
    partner_iso3    char(3)  NOT NULL REFERENCES dw.dim_country(iso3),
    ncm8            char(8)  NOT NULL,                                -- para Comtrade: SH6 + '00'
    hs6             char(6)  GENERATED ALWAYS AS (left(ncm8, 6)) STORED,
    uf              char(2)  NOT NULL DEFAULT '--',                   -- UF de origem/destino (Comex)
    urf_code        int      NOT NULL DEFAULT 0,                      -- URF de despacho (Comex)
    via_code        int      NOT NULL DEFAULT 0,                      -- via de transporte (Comex)
    value_usd_fob   numeric(18,2) NOT NULL,
    value_freight_usd  numeric(18,2),
    value_insurance_usd numeric(18,2),
    net_kg          numeric(18,3),
    qty_stat        numeric(18,3),
    stat_unit_code  int,
    qty_m3          numeric(18,3),
    qty_m3_method   text CHECK (qty_m3_method IN ('stat_unit','density','unavailable')),
    source_id       text   NOT NULL REFERENCES meta.source(source_id),
    run_id          bigint NOT NULL REFERENCES meta.etl_run(run_id),
    collected_at    timestamptz NOT NULL DEFAULT now(),
    version         int    NOT NULL DEFAULT 1,
    is_current      boolean NOT NULL DEFAULT true,
    superseded_at   timestamptz,
    superseded_by_run bigint REFERENCES meta.etl_run(run_id),
    is_simulated    boolean NOT NULL DEFAULT false
);
CREATE UNIQUE INDEX fact_trade_nk_current ON dw.fact_trade
    (flow, period, reporter_iso3, partner_iso3, ncm8, uf, urf_code, via_code, source_id, is_simulated)
    WHERE is_current;
CREATE INDEX fact_trade_period_idx  ON dw.fact_trade (period) WHERE is_current;
CREATE INDEX fact_trade_partner_idx ON dw.fact_trade (partner_iso3, period) WHERE is_current;
CREATE INDEX fact_trade_hs6_idx     ON dw.fact_trade (hs6, period) WHERE is_current;

-- ------------------------------ SÉRIES --------------------------------
-- Preços, fretes, câmbio (diário), macro, construção, produção…
CREATE TABLE dw.fact_series (
    obs_id          bigserial PRIMARY KEY,
    indicator_code  text   NOT NULL REFERENCES dw.dim_indicator(indicator_code),
    geo_iso3        char(3) NOT NULL REFERENCES dw.dim_country(iso3),
    period          date   NOT NULL,                  -- início do período (dia/mês/ano)
    value           numeric(20,6),                    -- NULL = dado indisponível declarado pela fonte
    obs_status      text   NOT NULL DEFAULT 'A' CHECK (obs_status IN ('A','P','E','M')), -- actual, provisional, estimate, missing
    source_id       text   NOT NULL REFERENCES meta.source(source_id),
    run_id          bigint NOT NULL REFERENCES meta.etl_run(run_id),
    collected_at    timestamptz NOT NULL DEFAULT now(),
    version         int    NOT NULL DEFAULT 1,
    is_current      boolean NOT NULL DEFAULT true,
    superseded_at   timestamptz,
    superseded_by_run bigint REFERENCES meta.etl_run(run_id),
    is_simulated    boolean NOT NULL DEFAULT false
);
CREATE UNIQUE INDEX fact_series_nk_current ON dw.fact_series
    (indicator_code, geo_iso3, period, source_id, is_simulated) WHERE is_current;
CREATE INDEX fact_series_ind_idx ON dw.fact_series (indicator_code, period) WHERE is_current;

-- ------------------------------ STAGING -------------------------------
CREATE UNLOGGED TABLE stg.trade (
    run_id          bigint NOT NULL,
    flow            char(1) NOT NULL,
    period          date    NOT NULL,
    reporter_code   text    NOT NULL,       -- código na fonte
    partner_code    text    NOT NULL,
    code_scheme     text    NOT NULL CHECK (code_scheme IN ('comex','iso3')),
    ncm8            char(8) NOT NULL,
    uf              char(2) NOT NULL DEFAULT '--',
    urf_code        int     NOT NULL DEFAULT 0,
    via_code        int     NOT NULL DEFAULT 0,
    value_usd_fob   numeric(18,2) NOT NULL,
    value_freight_usd  numeric(18,2),
    value_insurance_usd numeric(18,2),
    net_kg          numeric(18,3),
    qty_stat        numeric(18,3),
    stat_unit_code  int
);
CREATE INDEX stg_trade_run_idx ON stg.trade (run_id);

CREATE UNLOGGED TABLE stg.series (
    run_id          bigint NOT NULL,
    indicator_code  text   NOT NULL,
    geo_iso3        char(3) NOT NULL,
    period          date   NOT NULL,
    value           numeric(20,6),
    obs_status      text   NOT NULL DEFAULT 'A'
);
CREATE INDEX stg_series_run_idx ON stg.series (run_id);

-- Linhas rejeitadas na validação de linha (antes do merge)
CREATE TABLE dq.rejected_row (
    rejected_id bigserial PRIMARY KEY,
    run_id      bigint NOT NULL REFERENCES meta.etl_run(run_id) ON DELETE CASCADE,
    dataset     text   NOT NULL,
    reason      text   NOT NULL,
    row_data    jsonb  NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- =====================================================================
-- MERGE: staging → dw com versionamento
-- =====================================================================
CREATE OR REPLACE FUNCTION dw.merge_trade(p_run bigint)
RETURNS TABLE (inserted int, revised int, unchanged int, unmapped int)
LANGUAGE plpgsql AS $$
DECLARE
    v_sim boolean; v_src text;
    v_ins int := 0; v_rev int := 0; v_unc int := 0; v_unm int := 0;
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

    UPDATE dw.fact_trade f SET is_current = false, superseded_at = now(), superseded_by_run = p_run
    FROM _mt_c c WHERE c.st = 'revised' AND f.trade_id = c.trade_id;

    INSERT INTO dw.fact_trade (flow, period, reporter_iso3, partner_iso3, ncm8, uf, urf_code, via_code,
        value_usd_fob, value_freight_usd, value_insurance_usd, net_kg, qty_stat, stat_unit_code,
        qty_m3, qty_m3_method, source_id, run_id, version, is_simulated)
    SELECT c.flow, c.period, c.reporter_iso3, c.partner_iso3, c.ncm8, c.uf, c.urf_code, c.via_code,
           c.v, c.fr, c.ins, c.kg, c.q, c.su,
           CASE WHEN u.is_m3 THEN c.q
                WHEN p.density_kg_m3 IS NOT NULL AND c.kg IS NOT NULL THEN round(c.kg / p.density_kg_m3, 3)
           END,
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
    UPDATE meta.etl_run SET rows_inserted = v_ins, rows_revised = v_rev, rows_unchanged = v_unc
     WHERE run_id = p_run;
    RETURN QUERY SELECT v_ins, v_rev, v_unc, v_unm;
END $$;

CREATE OR REPLACE FUNCTION dw.merge_series(p_run bigint)
RETURNS TABLE (inserted int, revised int, unchanged int)
LANGUAGE plpgsql AS $$
DECLARE
    v_sim boolean; v_src text; v_ins int; v_rev int; v_unc int;
BEGIN
    SELECT r.is_simulated, r.source_id INTO v_sim, v_src FROM meta.etl_run r WHERE r.run_id = p_run;
    IF v_src IS NULL THEN RAISE EXCEPTION 'run % inexistente', p_run; END IF;

    DROP TABLE IF EXISTS _ms_c;
    CREATE TEMP TABLE _ms_c ON COMMIT DROP AS
    SELECT DISTINCT ON (s.indicator_code, s.geo_iso3, s.period)
           s.indicator_code, s.geo_iso3, s.period, s.value, s.obs_status,
           f.obs_id, f.version AS old_version,
           CASE WHEN f.obs_id IS NULL THEN 'new'
                WHEN f.value IS DISTINCT FROM s.value OR f.obs_status IS DISTINCT FROM s.obs_status THEN 'revised'
                ELSE 'same' END AS st
    FROM stg.series s
    LEFT JOIN dw.fact_series f
      ON f.is_current AND f.is_simulated = v_sim AND f.source_id = v_src
     AND f.indicator_code = s.indicator_code AND f.geo_iso3 = s.geo_iso3 AND f.period = s.period
    WHERE s.run_id = p_run
    ORDER BY s.indicator_code, s.geo_iso3, s.period;

    UPDATE dw.fact_series f SET is_current = false, superseded_at = now(), superseded_by_run = p_run
    FROM _ms_c c WHERE c.st = 'revised' AND f.obs_id = c.obs_id;

    INSERT INTO dw.fact_series (indicator_code, geo_iso3, period, value, obs_status, source_id, run_id, version, is_simulated)
    SELECT c.indicator_code, c.geo_iso3, c.period, c.value, c.obs_status, v_src, p_run,
           coalesce(c.old_version, 0) + 1, v_sim
    FROM _ms_c c WHERE c.st IN ('new','revised');

    SELECT count(*) FILTER (WHERE st = 'new'), count(*) FILTER (WHERE st = 'revised'),
           count(*) FILTER (WHERE st = 'same')
      INTO v_ins, v_rev, v_unc FROM _ms_c;

    DELETE FROM stg.series WHERE run_id = p_run;
    UPDATE meta.etl_run SET rows_inserted = v_ins, rows_revised = v_rev, rows_unchanged = v_unc
     WHERE run_id = p_run;
    RETURN QUERY SELECT v_ins, v_rev, v_unc;
END $$;

-- Consulta "como era este número em tal data?" (auditoria de revisões)
CREATE OR REPLACE FUNCTION dw.trade_as_of(p_at timestamptz)
RETURNS SETOF dw.fact_trade LANGUAGE sql STABLE AS $$
    SELECT * FROM dw.fact_trade
     WHERE collected_at <= p_at AND (superseded_at IS NULL OR superseded_at > p_at)
$$;
