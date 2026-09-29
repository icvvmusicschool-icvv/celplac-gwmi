-- 0022 — Papel de banco da API publicada (gwmi_api): lê tudo, escreve só configurações do índice.
-- A API na internet não usa o dono do banco (gwmi_owner). Se a senha dela vazar, quem a tiver
-- consegue ler, mas não alterar nem apagar dados, nem mudar o esquema.
--
-- O papel é criado no Console do Neon (Roles → New role → gwmi_api), para que a senha
-- nunca passe por código ou conversa. Depois de criado, rode:  SELECT meta.grant_api_role();
-- (esta migração já roda a função; se o papel ainda não existir, ela só avisa).
CREATE OR REPLACE FUNCTION meta.grant_api_role(p_role text DEFAULT 'gwmi_api')
RETURNS text LANGUAGE plpgsql AS $$
DECLARE s text;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = p_role) THEN
        RETURN format('papel %s ainda não existe: crie no Console do Neon e rode SELECT meta.grant_api_role();', p_role);
    END IF;
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), p_role);
    FOREACH s IN ARRAY ARRAY['meta','raw','dw','mart','intel','dq'] LOOP
        EXECUTE format('GRANT USAGE ON SCHEMA %I TO %I', s, p_role);
        EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA %I TO %I', s, p_role);
        EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT SELECT ON TABLES TO %I', s, p_role);
    END LOOP;
    EXECUTE format('GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA mart TO %I', p_role);
    -- funções de carga não servem à API
    EXECUTE format('REVOKE EXECUTE ON FUNCTION mart.derive_trade_series(bigint, text), mart.derive_fx_cross(bigint) FROM %I', p_role);
    -- única escrita: salvar uma configuração de pesos do índice (POST /v1/index com save_as)
    EXECUTE format('GRANT INSERT ON intel.index_config TO %I', p_role);
    EXECUTE format('GRANT USAGE ON ALL SEQUENCES IN SCHEMA intel TO %I', p_role);
    EXECUTE format('ALTER ROLE %I SET statement_timeout = %L', p_role, '20s');
    EXECUTE format('ALTER ROLE %I SET idle_in_transaction_session_timeout = %L', p_role, '30s');
    RETURN format('permissões aplicadas a %s', p_role);
END $$;
COMMENT ON FUNCTION meta.grant_api_role(text) IS 'Concede ao papel da API leitura em todos os esquemas e INSERT só em intel.index_config. Reaplicar após criar tabelas novas em esquemas novos.';

DO $$ BEGIN RAISE NOTICE '%', meta.grant_api_role(); END $$;
