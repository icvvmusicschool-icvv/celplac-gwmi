"""Gera o SQL de carga de um CSV do FRED (fredgraph.csv) para o Neon (ou qualquer PostgreSQL do GWMI).

O CSV original vai inteiro dentro do SQL: o banco calcula o SHA-256 dele, registra em raw.ingestion,
faz o parse para stg.series e roda dw.merge_series — mesmo contrato do pipeline Python.
Uso: python fred_csv_to_sql.py HOUST US_HOUSING_STARTS USA arquivo.csv [cosd] > carga.sql
"""
import json
import sys


def statements(series_id: str, indicator: str, geo: str, csv_text: str, cosd: str = "2000-01-01") -> list[str]:
    uri = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={cosd}"
    params = json.dumps({"series_id": series_id, "indicator": indicator, "geo": geo, "mode": "fredgraph.csv (sem chave)"})
    cur = "currval(pg_get_serial_sequence('meta.etl_run','run_id'))"
    val = "nullif(nullif(split_part(l, ',', 2), ''), '.')"
    return [
        f"""WITH r AS (INSERT INTO meta.etl_run (source_id, job, params, is_simulated)
      VALUES ('fred', 'fred.{series_id.lower()}', '{params}'::jsonb, false) RETURNING run_id),
 t AS (SELECT $csv${csv_text}$csv$::text AS c),
 raw AS (INSERT INTO raw.ingestion (run_id, source_id, uri, storage_path, content_sha256, bytes, http_status, meta)
      SELECT r.run_id, 'fred', '{uri}', '{uri} (payload original na fonte; SHA-256 calculado no banco sobre o CSV recebido)',
             encode(sha256(convert_to(t.c, 'UTF8')), 'hex'), octet_length(t.c), 200, '{{}}'::jsonb FROM r, t RETURNING 1)
INSERT INTO stg.series (run_id, indicator_code, geo_iso3, period, value, obs_status)
SELECT r.run_id, '{indicator}', '{geo}', split_part(l, ',', 1)::date, {val}::numeric,
       CASE WHEN {val} IS NULL THEN 'M' ELSE 'A' END
FROM r, t, regexp_split_to_table(t.c, E'\\n') l WHERE l ~ '^\\d{{4}}-\\d{{2}}-\\d{{2}},'""",
        f"SELECT * FROM dw.merge_series({cur})",
        f"""UPDATE meta.etl_run SET status = 'success', finished_at = now(),
       rows_staged = coalesce(rows_inserted, 0) + coalesce(rows_revised, 0) + coalesce(rows_unchanged, 0)
 WHERE run_id = {cur}""",
    ]


if __name__ == "__main__":
    sid, ind, geo, path = sys.argv[1:5]
    cosd = sys.argv[5] if len(sys.argv) > 5 else "2000-01-01"
    print(";\n".join(statements(sid, ind, geo, open(path, encoding="utf-8").read(), cosd)) + ";")
