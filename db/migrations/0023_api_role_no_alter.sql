-- 0023 — grant_api_role sem ALTER ROLE obrigatório.
-- No Neon, um papel criado pelo Console não pode ser alterado (ALTER ROLE ... SET) pelo dono do banco:
-- "permission denied to alter role". Os limites de tempo passam a ser opcionais; as permissões
-- (o que importa para a segurança) são aplicadas de qualquer forma.
CREATE OR REPLACE FUNCTION meta.grant_api_role(p_role text DEFAULT 'gwmi_api')
RETURNS text LANGUAGE plpgsql AS $$
DECLARE s text; extra text := '';
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
    EXECUTE format('REVOKE EXECUTE ON FUNCTION mart.derive_trade_series(bigint, text), mart.derive_fx_cross(bigint) FROM %I', p_role);
    EXECUTE format('GRANT INSERT ON intel.index_config TO %I', p_role);
    EXECUTE format('GRANT USAGE ON ALL SEQUENCES IN SCHEMA intel TO %I', p_role);
    BEGIN
        EXECUTE format('ALTER ROLE %I SET statement_timeout = %L', p_role, '20s');
        EXECUTE format('ALTER ROLE %I SET idle_in_transaction_session_timeout = %L', p_role, '30s');
    EXCEPTION WHEN insufficient_privilege THEN
        extra := ' (limites de tempo do papel não aplicados: sem permissão para ALTER ROLE)';
    END;
    RETURN format('permissões aplicadas a %s', p_role) || extra;
END $$;

DO $$ BEGIN RAISE NOTICE '%', meta.grant_api_role(); END $$;
