-- =====================================================================
-- CELPLAC GWMI · 0002 · Dimensões
-- =====================================================================

-- Países (ISO 3166). Agregados usam códigos próprios: WLD, EUU, XXX (não identificado)
CREATE TABLE dw.dim_country (
    iso3         char(3) PRIMARY KEY,
    iso2         char(2),
    m49          int,
    name_pt      text NOT NULL,
    name_en      text,
    region       text NOT NULL,        -- América do Norte, Europa, …
    subregion    text,
    is_mercosur  boolean NOT NULL DEFAULT false,
    is_eu        boolean NOT NULL DEFAULT false,
    is_aggregate boolean NOT NULL DEFAULT false,
    lat          numeric(7,3),
    lon          numeric(7,3)
);

-- Mapeamento do código de país do Comex Stat (CO_PAIS) → ISO3.
-- Carregado da tabela auxiliar oficial PAIS.csv (nunca digitado à mão).
CREATE TABLE dw.map_country_comex (
    co_pais     int PRIMARY KEY,
    iso3        char(3) REFERENCES dw.dim_country(iso3),
    iso3_source text,                  -- valor original CO_PAIS_ISOA3
    name_pt     text,
    run_id      bigint REFERENCES meta.etl_run(run_id)
);

CREATE TABLE dw.dim_uf (
    uf       char(2) PRIMARY KEY,
    name_pt  text NOT NULL,
    region   text NOT NULL
);

-- Famílias de produto da cadeia
CREATE TABLE dw.dim_product (
    product_code  text PRIMARY KEY,           -- PLYWOOD_CONIFER, VENEER_TROPICAL…
    family        text NOT NULL CHECK (family IN
                  ('roundwood','sawnwood','veneer','plywood','lvl','panels','other')),
    name_pt       text NOT NULL,
    name_en       text,
    density_kg_m3 numeric(7,1),               -- fator p/ converter kg → m³ quando não houver qtd. estatística em m³
    density_note  text,
    is_celplac_core boolean NOT NULL DEFAULT false
);

-- SH6 → produto (regra de classificação; NCM8 herda pelo prefixo)
CREATE TABLE dw.map_hs6_product (
    hs6          char(6) PRIMARY KEY,
    product_code text NOT NULL REFERENCES dw.dim_product(product_code),
    description_pt text NOT NULL,
    hs_edition   text NOT NULL DEFAULT 'HS2022',
    is_verified  boolean NOT NULL DEFAULT false,  -- conferido contra a NCM vigente?
    note         text
);

-- NCM 8 dígitos — carregada da tabela oficial NCM.csv do Comex Stat
CREATE TABLE dw.dim_ncm (
    ncm8         char(8) PRIMARY KEY,
    hs6          char(6) GENERATED ALWAYS AS (left(ncm8, 6)) STORED,
    hs4          char(4) GENERATED ALWAYS AS (left(ncm8, 4)) STORED,
    description_pt text NOT NULL,
    stat_unit_code int,
    stat_unit_name text,
    run_id       bigint REFERENCES meta.etl_run(run_id)
);
CREATE INDEX dim_ncm_hs6_idx ON dw.dim_ncm (hs6);

-- Portos / URFs. port_code = 'URF:<CO_URF>' para URFs do Comex ou UN/LOCODE p/ portos
CREATE TABLE dw.dim_port (
    port_code    text PRIMARY KEY,
    name         text NOT NULL,
    country_iso3 char(3) NOT NULL REFERENCES dw.dim_country(iso3),
    unlocode     char(5),
    kind         text NOT NULL CHECK (kind IN ('seaport','urf','dry_port','border')),
    lat          numeric(7,3),
    lon          numeric(7,3)
);

-- URF (Comex) → porto físico agrupador (Paranaguá, Itajaí/Itapoá…)
CREATE TABLE dw.map_urf_port (
    co_urf     int PRIMARY KEY,
    urf_name   text NOT NULL,
    port_code  text REFERENCES dw.dim_port(port_code),
    run_id     bigint REFERENCES meta.etl_run(run_id)
);

-- Unidades estatísticas (NCM_UNIDADE.csv)
CREATE TABLE dw.dim_stat_unit (
    co_unid   int PRIMARY KEY,
    name      text NOT NULL,
    is_m3     boolean GENERATED ALWAYS AS (upper(name) LIKE 'METRO C%BICO%') STORED
);

-- Indicadores (séries temporais). kind segue o princípio DADO/INDICADOR
CREATE TABLE dw.dim_indicator (
    indicator_code text PRIMARY KEY,           -- 'FX_USD_BRL', 'US_HOUSING_STARTS'…
    name_pt        text NOT NULL,
    unit           text NOT NULL,
    frequency      text NOT NULL CHECK (frequency IN ('D','W','M','Q','A')),
    kind           text NOT NULL CHECK (kind IN ('data','indicator')),
    polarity       smallint NOT NULL DEFAULT 1 CHECK (polarity IN (-1,0,1)), -- leitura p/ exportador (hipótese)
    category       text NOT NULL,              -- price, freight, fx, macro, construction, trade, production
    source_id      text NOT NULL REFERENCES meta.source(source_id),
    source_ref     text,                       -- código na fonte (ex. série FRED 'HOUST')
    formula        text,                       -- para kind='indicator'
    pulse_key      text UNIQUE,                -- chave no Market Pulse (WOOD, PLYWOOD…)
    description    text
);

-- Calendário mensal
CREATE TABLE dw.dim_month (
    period   date PRIMARY KEY CHECK (extract(day FROM period) = 1),
    year     int NOT NULL,
    month    int NOT NULL,
    quarter  int NOT NULL,
    label_pt text NOT NULL
);
INSERT INTO dw.dim_month
SELECT d::date, extract(year FROM d)::int, extract(month FROM d)::int, extract(quarter FROM d)::int,
       (ARRAY['jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez'])[extract(month FROM d)::int]
       || '/' || to_char(d, 'YY')
FROM generate_series(date '2000-01-01', date '2035-12-01', interval '1 month') d;
