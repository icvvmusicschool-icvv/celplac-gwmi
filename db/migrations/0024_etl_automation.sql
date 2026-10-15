-- 0024 — ETL automático (GitHub Actions).
-- 1) Execução "unchanged": a fonte foi consultada, o arquivo é idêntico ao da última carga
--    (mesmo SHA-256 para o mesmo endereço) e nada foi reprocessado. Fica registrada para mostrar
--    que a verificação aconteceu.
ALTER TABLE meta.etl_run DROP CONSTRAINT IF EXISTS etl_run_status_check;
ALTER TABLE meta.etl_run ADD CONSTRAINT etl_run_status_check
    CHECK (status IN ('running','success','partial','failed','unchanged'));

-- 2) Papel de carga (gwmi_etl): grava dados, não altera o esquema. Criado pelo SQL Editor do Neon
--    (papéis criados pela tela Roles entram em neon_superuser):
--      CREATE ROLE gwmi_etl LOGIN PASSWORD '…';  SELECT meta.grant_etl_role();
CREATE OR REPLACE FUNCTION meta.grant_etl_role(p_role text DEFAULT 'gwmi_etl')
RETURNS text LANGUAGE plpgsql AS $$
DECLARE s text;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = p_role) THEN
        RETURN format('papel %s ainda não existe: crie no SQL Editor e rode SELECT meta.grant_etl_role();', p_role);
    END IF;
    EXECUTE format('GRANT CONNECT, TEMPORARY ON DATABASE %I TO %I', current_database(), p_role);
    FOREACH s IN ARRAY ARRAY['meta','raw','stg','dw','dq','intel','mart'] LOOP
        EXECUTE format('GRANT USAGE ON SCHEMA %I TO %I', s, p_role);
        EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA %I TO %I', s, p_role);
        EXECUTE format('GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA %I TO %I', s, p_role);
        EXECUTE format('GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA %I TO %I', s, p_role);
        EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I', s, p_role);
        EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO %I', s, p_role);
    END LOOP;
    -- as funções de concessão de papel não são da carga
    EXECUTE format('REVOKE EXECUTE ON FUNCTION meta.grant_api_role(text), meta.grant_etl_role(text) FROM %I', p_role);
    RETURN format('permissões de carga aplicadas a %s', p_role);
END $$;
REVOKE EXECUTE ON FUNCTION meta.grant_etl_role(text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION meta.grant_api_role(text) FROM PUBLIC;

DO $$ BEGIN RAISE NOTICE '%', meta.grant_etl_role(); END $$;
