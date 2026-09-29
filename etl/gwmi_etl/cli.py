"""CLI do ETL.  Ex.:  gwmi-etl seed-demo   ·   gwmi-etl comex-trade --flow X --year 2025"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import date
from pathlib import Path

import click

from .config import settings
from .db import connect

ROOT = Path(__file__).resolve().parents[2]


def _db():
    return connect(settings().database_url)


def _echo_report(rep):
    click.echo(rep.summary())
    if rep.status == "failed":
        raise SystemExit(1)


@click.group()
@click.option("-v", "--verbose", is_flag=True)
def main(verbose):
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format="%(levelname)s %(message)s")


@main.command("migrate")
@click.option("--dir", "mig_dir", type=click.Path(path_type=Path),
              default=lambda: Path(os.environ.get("GWMI_MIGRATIONS_DIR", ROOT / "db" / "migrations")))
def migrate(mig_dir: Path):
    """Aplica migrações pendentes (mesma lógica de db/migrate.sh)."""
    db = _db()
    db.execute("""CREATE SCHEMA IF NOT EXISTS meta; CREATE TABLE IF NOT EXISTS meta.schema_migrations
                  (version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now(), checksum text NOT NULL)""")
    for f in sorted(mig_dir.glob("*.sql")):
        v, body = f.stem, f.read_bytes()
        sha = hashlib.sha256(body).hexdigest()
        cur = db.scalar("SELECT checksum FROM meta.schema_migrations WHERE version = %(v)s", {"v": v})
        if cur:
            if cur != sha:
                raise click.ClickException(f"{v} já aplicada com checksum diferente — crie nova migração")
            continue
        click.echo(f"→ aplicando {v}")
        with db.transaction():
            db.conn.execute(body.decode("utf-8"))
            db.execute("INSERT INTO meta.schema_migrations (version, checksum) VALUES (%(v)s, %(c)s)", {"v": v, "c": sha})
    click.echo("✓ migrações em dia")


@main.command("seed-demo")
def seed_demo():
    """Carrega o conjunto DEMO completo (is_simulated=true) e recalcula derivados e sinais."""
    from .demo import DEMO_DATA, DemoSeriesJob, DemoTradeJob
    from .jobs import import_intel, run_derive, run_signals
    from .pipeline import run_job

    db, s = _db(), settings()
    for job in (DemoTradeJob(), DemoSeriesJob()):
        _echo_report(run_job(db, job, s))
    for kind in ("events", "news"):
        click.echo(f"intel {kind}: {import_intel(db, DEMO_DATA / f'{kind}.jsonl', kind, is_simulated=True)}")
    for g in ("br_exports", "market_imports", "fx_cross"):
        click.echo(f"derive {g}: {run_derive(db, g)}")
    res = run_signals(db, date(2026, 8, 1))
    click.echo(f"sinais avaliados: {len(res)}")


@main.command("comex-reference")
@click.option("--dir", "local_dir", type=click.Path(exists=True, path_type=Path), default=None,
              help="Pasta com PAIS.csv, NCM_UNIDADE.csv, NCM.csv, URF.csv (senão baixa do portal)")
def comex_reference(local_dir):
    """Carrega tabelas auxiliares oficiais (países, NCM cap. 44, unidades, URF)."""
    from .connectors.comexstat import REF_ORDER, run_comex_reference
    files = {t: local_dir / f"{t}.csv" for t in REF_ORDER if (local_dir / f"{t}.csv").exists()} if local_dir else None
    for r in run_comex_reference(_db(), settings(), files):
        click.echo(r)


@main.command("comex-trade")
@click.option("--flow", type=click.Choice(["X", "M"]), required=True)
@click.option("--year", type=int, required=True)
@click.option("--file", type=click.Path(exists=True, path_type=Path), default=None)
def comex_trade(flow, year, file):
    """Exportações (X) ou importações (M) brasileiras do cap. 44 para um ano."""
    from .connectors.comexstat import ComexTradeJob
    from .jobs import run_derive
    from .pipeline import run_job
    db = _db()
    _echo_report(run_job(db, ComexTradeJob(flow, year, file), settings()))
    click.echo(f"derive: {run_derive(db, 'br_exports')}")


@main.command("ptax")
@click.option("--currency", "-c", multiple=True, default=["USD", "EUR", "GBP"])
@click.option("--start", type=click.DateTime(["%Y-%m-%d"]), required=True)
@click.option("--end", type=click.DateTime(["%Y-%m-%d"]), default=str(date.today()))
@click.option("--file", type=click.Path(exists=True, path_type=Path), default=None)
def ptax(currency, start, end, file):
    """Câmbio PTAX (boletim de fechamento)."""
    from .connectors.series_sources import PtaxJob
    from .pipeline import run_job
    db = _db()
    for c in currency:
        _echo_report(run_job(db, PtaxJob(c, start.date(), end.date(), file), settings()))


FRED_DEFAULT = (("HOUST", "US_HOUSING_STARTS", "USA", "2000-01-01"),
                ("HOUST1F", "US_HOUSING_STARTS_1F", "USA", "2000-01-01"),
                ("PERMIT", "US_BUILDING_PERMITS", "USA", "2000-01-01"),
                ("DEXMXUS", "FX_USD_MXN", "MEX", "2021-01-01"),
                ("DEXCHUS", "FX_USD_CNY", "CHN", "2021-01-01"))


@main.command("fred")
@click.option("--series", "series_id", default=None, help="ex.: HOUST (omitir = conjunto padrão do GWMI)")
@click.option("--indicator", default=None, help="ex.: US_HOUSING_STARTS")
@click.option("--geo", default="USA")
@click.option("--start", type=click.DateTime(["%Y-%m-%d"]), default=None)
@click.option("--file", type=click.Path(exists=True, path_type=Path), default=None)
def fred(series_id, indicator, geo, start, file):
    """FRED: API com FRED_API_KEY; sem chave usa o fredgraph.csv público."""
    from .connectors.series_sources import FredJob
    from .jobs import run_derive
    from .pipeline import run_job
    db = _db()
    todo = [(series_id, indicator, geo, start.date().isoformat() if start else "2000-01-01")] if series_id else FRED_DEFAULT
    for sid, ind, g, st in todo:
        if not ind:
            raise click.UsageError("--indicator é obrigatório com --series")
        _echo_report(run_job(db, FredJob(sid, ind, g, date.fromisoformat(st), file=file), settings()))
    if any(t[0].startswith("DEX") for t in todo):
        click.echo(f"derive: {run_derive(db, 'fx_cross')}")


@main.command("sidra")
@click.option("--path", required=True, help="ex.: /t/291/n1/all/v/all/p/all/c194/all (confirmar tabela)")
@click.option("--indicator", required=True)
@click.option("--match", required=True, help='JSON {"Rótulo da dimensão": "categoria"}')
@click.option("--scale", type=float, default=1.0)
@click.option("--file", type=click.Path(exists=True, path_type=Path), default=None)
def sidra(path, indicator, match, scale, file):
    from .connectors.series_sources import SidraJob
    from .pipeline import run_job
    _echo_report(run_job(_db(), SidraJob(path, indicator, json.loads(match), scale, file), settings()))


@main.command("pevs")
@click.option("--file", type=click.Path(exists=True, path_type=Path), default=None)
def pevs(file):
    """IBGE PEVS (tabela 291): tora de pinus e eucalipto, total e 'outras finalidades'."""
    from .connectors.series_sources import PevsJob
    from .pipeline import run_job
    _echo_report(run_job(_db(), PevsJob(file), settings()))


@main.command("pim-wood")
@click.option("--file", type=click.Path(exists=True, path_type=Path), default=None)
def pim_wood(file):
    """IBGE PIM-PF (tabela 8888): produção física de produtos de madeira, dessazonalizada."""
    from .connectors.series_sources import PIM_WOOD, SidraJob
    from .pipeline import run_job
    _echo_report(run_job(_db(), SidraJob(PIM_WOOD["path"], PIM_WOOD["indicator"], PIM_WOOD["match"], 1.0, file), settings()))


@main.command("comtrade-preview")
@click.option("--cmd", "-c", multiple=True, default=["4412", "4408", "4407"])
@click.option("--flow", type=click.Choice(["X", "M"]), default="X")
@click.option("--period", "-p", multiple=True, required=True, help="AAAA (anual) ou AAAAMM (mensal); um por consulta")
@click.option("--partner", default="0", help="0 = mundo; 0,76 = mundo e Brasil")
def comtrade_preview(cmd, flow, period, partner):
    """UN Comtrade sem chave (API pública de pré-visualização)."""
    import time
    from .connectors.comtrade import ComtradePreviewJob
    from .jobs import run_derive
    from .pipeline import run_job
    db = _db()
    for c in cmd:
        for p in period:
            _echo_report(run_job(db, ComtradePreviewJob(c, flow, p, "A" if len(p) == 4 else "M", partner), settings()))
            time.sleep(1.5)
    if flow == "M":
        click.echo(f"derive: {run_derive(db, 'market_imports')}")


@main.command("comtrade")
@click.option("--reporter", required=True, help="código M49 do reporter, ex.: 842 (EUA na Comtrade)")
@click.option("--periods", required=True, help="ex.: 202501,202502")
@click.option("--cmd", default="4412")
@click.option("--partner", default="0")
@click.option("--flow", default="M,X")
@click.option("--freq", type=click.Choice(["M", "A"]), default="M")
@click.option("--file", type=click.Path(exists=True, path_type=Path), default=None)
def comtrade(reporter, periods, cmd, partner, flow, freq, file):
    from .connectors.comtrade import ComtradeJob
    from .jobs import run_derive
    from .pipeline import run_job
    db = _db()
    _echo_report(run_job(db, ComtradeJob(reporter, periods, cmd, partner, flow, freq, file), settings()))
    click.echo(f"derive: {run_derive(db, 'market_imports')}")


@main.command("faostat")
@click.option("--file", type=click.Path(exists=True, path_type=Path), required=True)
def faostat(file):
    from .connectors.series_sources import FaostatJob
    from .pipeline import run_job
    _echo_report(run_job(_db(), FaostatJob(file), settings()))


@main.command("manual")
@click.option("--file", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--source", required=True, help="source_id em meta.source (ex.: drewry, itto, anfir)")
def manual(file, source):
    """CSV manual para fontes licenciadas ou sem API."""
    from .connectors.series_sources import ManualSeriesJob
    from .pipeline import run_job
    _echo_report(run_job(_db(), ManualSeriesJob(file, source), settings()))


@main.command("intel")
@click.option("--kind", type=click.Choice(["events", "news"]), required=True)
@click.option("--file", type=click.Path(exists=True, path_type=Path), required=True)
def intel(kind, file):
    """Importa eventos geopolíticos ou notícias classificadas (JSON Lines)."""
    from .jobs import import_intel
    click.echo(import_intel(_db(), file, kind))


@main.command("derive")
def derive():
    from .jobs import run_derive
    db = _db()
    for g in ("br_exports", "market_imports", "fx_cross"):
        click.echo(run_derive(db, g))


@main.command("signals")
@click.option("--as-of", type=click.DateTime(["%Y-%m-%d"]), default=None)
def signals(as_of):
    from .jobs import run_signals
    for r in run_signals(_db(), as_of.date() if as_of else None):
        click.echo(r)


@main.command("dq")
def dq():
    """Executa todas as regras de qualidade."""
    for r in _db().query("SELECT * FROM dq.run_checks()"):
        click.echo(f"{'✓' if r['passed'] else '✗'} {r['rule_id']} ({r['severity']}): {r['failing']}")


@main.command("status")
def status():
    """Situação de cada fonte (integrada, simulada, sem dados)."""
    for r in _db().query("SELECT source_id, integration_status, last_period, last_run_status FROM dq.v_source_quality ORDER BY 1"):
        click.echo(f"{r['source_id']:<12} {r['integration_status']:<11} último período: {r['last_period']}  run: {r['last_run_status']}")


if __name__ == "__main__":
    main()
