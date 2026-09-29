-- =====================================================================
-- CELPLAC GWMI · 0004 · Inteligência: eventos, notícias, sinais, índice,
-- notas analíticas e alertas. Princípio: DADO ≠ INDICADOR ≠ ANÁLISE ≠
-- HIPÓTESE ≠ ALERTA — o tipo é coluna obrigatória, não convenção.
-- =====================================================================
CREATE TYPE intel.epistemic_kind AS ENUM ('data','indicator','trend','analysis','hypothesis','alert');
CREATE TYPE intel.impact_level   AS ENUM ('ALTO','MÉDIO','BAIXO','INDETERMINADO');
CREATE TYPE intel.confidence     AS ENUM ('ALTA','MÉDIA','BAIXA');
CREATE TYPE intel.impact_class   AS ENUM ('direto','indireto','contexto','monitoramento');

CREATE TABLE intel.geo_event (
    event_id        text PRIMARY KEY,
    category        text NOT NULL CHECK (category IN
                    ('TRADE WAR','TARIFFS','SANCTIONS','CONFLICTS','SHIPPING','ENERGY','CHINA','USA','EUROPE','BRAZIL','MERCOSUL')),
    title           text NOT NULL,
    event_date      date NOT NULL,
    countries       char(3)[] NOT NULL DEFAULT '{}',
    hs6_affected    char(6)[] NOT NULL DEFAULT '{}',
    products_text   text,
    routes          text,
    potential_impact intel.impact_level NOT NULL DEFAULT 'INDETERMINADO',
    confidence      intel.confidence NOT NULL DEFAULT 'BAIXA',
    evidence        text NOT NULL,                      -- obrigatório: sem evidência, sem evento
    source_name     text NOT NULL,
    source_url      text,
    impact_class    intel.impact_class NOT NULL DEFAULT 'monitoramento',
    status          text NOT NULL DEFAULT 'aberto' CHECK (status IN ('aberto','em_monitoramento','encerrado')),
    is_simulated    boolean NOT NULL DEFAULT false,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT impact_needs_confidence CHECK (potential_impact = 'INDETERMINADO' OR confidence IS NOT NULL)
);
CREATE INDEX geo_event_date_idx ON intel.geo_event (event_date DESC);

CREATE TABLE intel.news_item (
    news_id         bigserial PRIMARY KEY,
    published_at    timestamptz NOT NULL,
    title           text NOT NULL,
    source_name     text NOT NULL,
    url             text,
    url_sha256      char(64) UNIQUE,                    -- deduplicação
    country_iso3    char(3)[] NOT NULL DEFAULT '{}',
    category        text NOT NULL,
    summary         text,
    products_text   text,
    hs6_affected    char(6)[] NOT NULL DEFAULT '{}',
    impact_class    intel.impact_class NOT NULL,
    potential_impact intel.impact_level NOT NULL DEFAULT 'INDETERMINADO',
    classified_by   text NOT NULL DEFAULT 'rule' CHECK (classified_by IN ('rule','analyst','model')),
    event_id        text REFERENCES intel.geo_event(event_id),
    is_simulated    boolean NOT NULL DEFAULT false,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX news_pub_idx ON intel.news_item (published_at DESC);

-- Regras de early warning (versionadas). conditions = lista de condições:
-- [{"label":"Exportações BR ↓","indicator":"EXP_BR_VALUE","geo":"{market}","test":"down","window":3,"threshold":0.01}, …]
CREATE TABLE intel.signal_rule (
    rule_id     text NOT NULL,
    version     int  NOT NULL DEFAULT 1,
    name        text NOT NULL,
    tone        text NOT NULL CHECK (tone IN ('pos','neg','warn')),
    conditions  jsonb NOT NULL,
    markets     char(3)[] NOT NULL,
    min_met_for_indication int NOT NULL DEFAULT 3,
    is_active   boolean NOT NULL DEFAULT true,
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (rule_id, version)
);

CREATE TABLE intel.signal_state (
    rule_id      text NOT NULL,
    rule_version int  NOT NULL,
    market_iso3  char(3) NOT NULL,
    as_of        date NOT NULL,
    conditions_met int NOT NULL,
    conditions_total int NOT NULL,
    detail       jsonb NOT NULL,                        -- estado de cada condição + valores usados
    result       text NOT NULL CHECK (result IN ('SINAL','INDICAÇÃO','SEM SINAL','EVIDÊNCIA INSUFICIENTE')),
    is_simulated boolean NOT NULL,
    computed_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (rule_id, rule_version, market_iso3, as_of, is_simulated),
    FOREIGN KEY (rule_id, rule_version) REFERENCES intel.signal_rule(rule_id, version)
);

-- Configurações do índice (pesos nunca "definitivos": cada config é registrada)
CREATE TABLE intel.index_config (
    config_id   bigserial PRIMARY KEY,
    name        text NOT NULL,
    components  jsonb NOT NULL,     -- [{"indicator":"CONSTRUCTION_COMPOSITE","geo":"WLD","weight":10,"invert":false}, …]
    method      text NOT NULL DEFAULT 'zscore_weighted',
    is_default  boolean NOT NULL DEFAULT false,
    created_by  text NOT NULL DEFAULT 'system',
    created_at  timestamptz NOT NULL DEFAULT now(),
    note        text
);
CREATE UNIQUE INDEX index_config_default ON intel.index_config (is_default) WHERE is_default;

-- Notas analíticas e hipóteses — ligadas a evidências (séries, eventos, notícias)
CREATE TABLE intel.analysis_note (
    note_id     bigserial PRIMARY KEY,
    kind        intel.epistemic_kind NOT NULL CHECK (kind IN ('analysis','hypothesis','trend')),
    title       text NOT NULL,
    body        text NOT NULL,
    refs        jsonb NOT NULL DEFAULT '[]'::jsonb,   -- [{"type":"series","indicator":"…","geo":"USA"}, {"type":"event","id":"E1"}]
    confidence  intel.confidence,
    status      text NOT NULL DEFAULT 'aberta' CHECK (status IN ('aberta','confirmada','refutada')),
    author      text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    reviewed_at timestamptz
);

CREATE TABLE intel.alert (
    alert_id    bigserial PRIMARY KEY,
    alert_type  text NOT NULL CHECK (alert_type IN ('TARIFA','LOGÍSTICA','DEMANDA','OPORTUNIDADE','GEOPOLÍTICA','CUSTO','CÂMBIO')),
    severity    text NOT NULL CHECK (severity IN ('red','orange','yellow','green','blue')),
    message     text NOT NULL,
    refs        jsonb NOT NULL DEFAULT '[]'::jsonb,
    triggered_by text NOT NULL,                        -- 'rule:<id>' | 'analyst' | 'event:<id>'
    is_simulated boolean NOT NULL DEFAULT false,
    created_at  timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz
);

-- ------------------------- CELPLAC (Fase 5) ---------------------------
CREATE TABLE celplac.sales (
    sale_line_id  bigserial PRIMARY KEY,
    invoice_date  date NOT NULL,
    product_sku   text NOT NULL,
    product_code  text REFERENCES dw.dim_product(product_code),
    ncm8          char(8),
    customer_id   text NOT NULL,
    country_iso3  char(3) REFERENCES dw.dim_country(iso3),
    currency      char(3) NOT NULL,
    qty_m3        numeric(14,3),
    value_currency numeric(16,2),
    value_brl     numeric(16,2),
    margin_brl    numeric(16,2),
    port_code     text REFERENCES dw.dim_port(port_code),
    run_id        bigint REFERENCES meta.etl_run(run_id)
);
