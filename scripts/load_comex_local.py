"""Carga local das tabelas oficiais + exportações Comex Stat (arquivos já baixados).
Uso: python scripts/load_comex_local.py <pasta_com_csvs> <dsn> [anos...]"""
import os, subprocess, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "core"), str(ROOT / "etl"), str(ROOT / "tests")]
from support.psql_db import PsqlDatabase  # troque por gwmi_etl.db.PsycopgDatabase se tiver psycopg
from gwmi_etl.config import Settings
from gwmi_etl.connectors.comexstat import REF_ORDER, ComexTradeJob, run_comex_reference
from gwmi_etl.pipeline import run_job
from gwmi_etl.jobs import run_derive

src, dsn, years = Path(sys.argv[1]), sys.argv[2], [int(y) for y in sys.argv[3:]] or [2025, 2026]
env = {**os.environ, "PGOPTIONS": "-c client_min_messages=warning"}
subprocess.run([str(ROOT / "db" / "migrate.sh")], check=True, env={**env, "DATABASE_URL": dsn}, stdout=subprocess.DEVNULL)
db = PsqlDatabase(dsn)
S = Settings(database_url=dsn, raw_dir=Path(os.environ.get("GWMI_RAW_DIR", "./data/raw")))
t = time.time()
refs = {k: src / f"{k}.csv" for k in REF_ORDER}
if os.environ.get("PAIS_BLOCO_FILE"):
    refs["PAIS_BLOCO"] = Path(os.environ["PAIS_BLOCO_FILE"])
for r in run_comex_reference(db, S, refs):
    print(r, flush=True)
for y in years:
    print(run_job(db, ComexTradeJob("X", y, src / f"EXP_{y}.csv"), S).summary(), flush=True)
print(run_derive(db, "br_exports"), flush=True)
print("segundos:", round(time.time() - t, 1))
