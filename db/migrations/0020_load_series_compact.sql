-- 0020 — Carga assistida de uma série num único comando (para quando o ETL Python não alcança o banco).
-- Faz o mesmo que o pipeline: meta.etl_run → raw.ingestion (SHA-256 do arquivo original, calculado na coleta)
-- → stg.series → dw.merge_series (versionado) → fecha o run. Dados no formato compacto
-- 'AAAA-MM=valor;AAAA-MM-DD=valor;…' ('' ou '.' como valor = ausente, obs_status 'M').
CREATE OR REPLACE FUNCTION stg.load_series_compact(
    p_source text, p_job text, p_params jsonb, p_uri text, p_sha256 text, p_bytes bigint,
    p_indicator text, p_geo char(3), p_data text)
RETURNS TABLE (run_id bigint, staged int, inserted int, revised int, unchanged int)
LANGUAGE plpgsql AS $$
DECLARE v_run bigint; v_n int; m record;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM dw.dim_indicator WHERE indicator_code = p_indicator) THEN
        RAISE EXCEPTION 'indicador % não cadastrado em dw.dim_indicator', p_indicator;
    END IF;
    INSERT INTO meta.etl_run (source_id, job, params, is_simulated)
    VALUES (p_source, p_job, coalesce(p_params, '{}'::jsonb) || jsonb_build_object('mode', 'carga assistida (load_series_compact)'), false)
    RETURNING meta.etl_run.run_id INTO v_run;
    INSERT INTO raw.ingestion (run_id, source_id, uri, storage_path, content_sha256, bytes, http_status, meta)
    VALUES (v_run, p_source, p_uri, 'payload original na fonte; SHA-256 calculado no momento da coleta', p_sha256, p_bytes, 200,
            jsonb_build_object('indicator', p_indicator, 'geo', p_geo));
    INSERT INTO stg.series (run_id, indicator_code, geo_iso3, period, value, obs_status)
    SELECT v_run, p_indicator, p_geo,
           CASE WHEN length(split_part(kv, '=', 1)) = 7 THEN (split_part(kv, '=', 1) || '-01')::date
                WHEN length(split_part(kv, '=', 1)) = 4 THEN (split_part(kv, '=', 1) || '-01-01')::date
                ELSE split_part(kv, '=', 1)::date END,
           nullif(nullif(split_part(kv, '=', 2), ''), '.')::numeric,
           CASE WHEN nullif(nullif(split_part(kv, '=', 2), ''), '.') IS NULL THEN 'M' ELSE 'A' END
    FROM regexp_split_to_table(p_data, ';') kv WHERE kv <> '';
    GET DIAGNOSTICS v_n = ROW_COUNT;
    SELECT * INTO m FROM dw.merge_series(v_run);
    UPDATE meta.etl_run SET status = 'success', finished_at = now(), rows_staged = v_n WHERE meta.etl_run.run_id = v_run;
    RETURN QUERY SELECT v_run, v_n, m.inserted, m.revised, m.unchanged;
END $$;
