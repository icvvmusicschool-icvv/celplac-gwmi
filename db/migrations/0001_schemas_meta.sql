-- =====================================================================
-- CELPLAC GWMI · 0001 · Schemas, metadados, catálogo de fontes, execuções
-- Camadas: raw → stg → dw → mart (indicadores) · intel · dq · meta
-- =====================================================================
CREATE SCHEMA IF NOT EXISTS meta;   -- fontes, execuções de ETL, configuração
CREATE SCHEMA IF NOT EXISTS raw;    -- registro dos payloads originais (arquivo + hash)
CREATE SCHEMA IF NOT EXISTS stg;    -- staging por execução (UNLOGGED)
CREATE SCHEMA IF NOT EXISTS dw;     -- data warehouse: dimensões e fatos versionados
CREATE SCHEMA IF NOT EXISTS mart;   -- indicadores e funções analíticas consumidas pela API
CREATE SCHEMA IF NOT EXISTS intel;  -- eventos, notícias, sinais, índice, notas analíticas
CREATE SCHEMA IF NOT EXISTS dq;     -- qualidade de dados
CREATE SCHEMA IF NOT EXISTS celplac;-- dados internos (Fase 5) — apenas estrutura

-- ---------------------------------------------------------------------
-- Catálogo de fontes
-- ---------------------------------------------------------------------
CREATE TABLE meta.source (
    source_id        text PRIMARY KEY,                 -- 'comexstat', 'bcb_ptax', 'demo'…
    name             text NOT NULL,
    url              text,
    source_type      text NOT NULL CHECK (source_type IN
                     ('oficial','organismo_internacional','setorial','especializada','jornalistica','interna','simulada')),
    periodicity      text NOT NULL,                    -- 'diária','mensal','anual'…
    coverage         text,
    methodology      text,
    license_note     text,
    expected_lag_days int,                             -- defasagem normal de publicação
    reliability      text CHECK (reliability IN ('ALTA','MÉDIA','BAIXA')),
    is_active        boolean NOT NULL DEFAULT true,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- Execuções de ETL (toda linha de fato aponta para o run que a gerou)
-- ---------------------------------------------------------------------
CREATE TABLE meta.etl_run (
    run_id        bigserial PRIMARY KEY,
    source_id     text NOT NULL REFERENCES meta.source(source_id),
    job           text NOT NULL,                       -- 'comexstat.trade', 'bcb.ptax'…
    params        jsonb NOT NULL DEFAULT '{}'::jsonb,
    status        text NOT NULL DEFAULT 'running'
                  CHECK (status IN ('running','success','partial','failed')),
    started_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz,
    rows_extracted int DEFAULT 0,
    rows_staged    int DEFAULT 0,
    rows_rejected  int DEFAULT 0,
    rows_inserted  int DEFAULT 0,
    rows_revised   int DEFAULT 0,
    rows_unchanged int DEFAULT 0,
    is_simulated  boolean NOT NULL DEFAULT false,
    error         text
);
CREATE INDEX etl_run_source_idx ON meta.etl_run (source_id, started_at DESC);

-- ---------------------------------------------------------------------
-- RAW: cada arquivo/resposta baixado fica registrado com hash e caminho
-- (o conteúdo em si vai para storage de arquivos — local ou S3)
-- ---------------------------------------------------------------------
CREATE TABLE raw.ingestion (
    ingestion_id   bigserial PRIMARY KEY,
    run_id         bigint NOT NULL REFERENCES meta.etl_run(run_id) ON DELETE CASCADE,
    source_id      text NOT NULL REFERENCES meta.source(source_id),
    uri            text NOT NULL,                      -- URL ou caminho de origem
    storage_path   text NOT NULL,                      -- onde o payload original foi guardado
    content_sha256 char(64) NOT NULL,
    bytes          bigint NOT NULL,
    http_status    int,
    fetched_at     timestamptz NOT NULL DEFAULT now(),
    meta           jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX ingestion_run_idx ON raw.ingestion (run_id);
CREATE INDEX ingestion_hash_idx ON raw.ingestion (content_sha256);

-- Configuração chave-valor (limiares de ciclo, flags)
CREATE TABLE meta.setting (
    key        text PRIMARY KEY,
    value      jsonb NOT NULL,
    description text,
    updated_at timestamptz NOT NULL DEFAULT now()
);
