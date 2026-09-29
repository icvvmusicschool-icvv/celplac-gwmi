"""Pipeline padrão: FONTE → RAW → STAGING → VALIDAÇÃO → DW (merge versionado) → DQ.

Cada execução gera um meta.etl_run. Todo payload original é guardado no
raw store com SHA-256 e registrado em raw.ingestion, de modo que qualquer
número do DW possa ser rastreado até o arquivo de onde veio.
"""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from itertools import islice
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

from .config import Settings
from .db import Database
from .validation import validate_series_row, validate_trade_row

log = logging.getLogger("gwmi.etl")

TRADE_COLUMNS = ("run_id", "flow", "period", "reporter_code", "partner_code", "code_scheme", "ncm8", "uf",
                 "urf_code", "via_code", "value_usd_fob", "value_freight_usd", "value_insurance_usd",
                 "net_kg", "qty_stat", "stat_unit_code")
SERIES_COLUMNS = ("run_id", "indicator_code", "geo_iso3", "period", "value", "obs_status")
BATCH = 50_000


# ----------------------------------------------------------------------
# Raw store
# ----------------------------------------------------------------------
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class RawStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def _dest(self, source_id: str, name: str, sha: str) -> Path:
        d = self.root / source_id / datetime.now(timezone.utc).strftime("%Y/%m/%d")
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{sha[:12]}_{name}"

    def put_file(self, source_id: str, src: Path, name: str | None = None) -> tuple[Path, str, int]:
        sha = sha256_file(src)
        dest = self._dest(source_id, name or src.name, sha)
        if not dest.exists():
            shutil.copyfile(src, dest)
        return dest, sha, dest.stat().st_size

    def put_bytes(self, source_id: str, data: bytes, name: str) -> tuple[Path, str, int]:
        sha = hashlib.sha256(data).hexdigest()
        dest = self._dest(source_id, name, sha)
        if not dest.exists():
            dest.write_bytes(data)
        return dest, sha, len(data)


def http_download(url: str, settings: Settings, params: dict | None = None,
                  headers: dict | None = None) -> tuple[Path, int]:
    """Baixa em streaming para arquivo temporário. Retorna (caminho, status HTTP)."""
    import httpx

    h = {"User-Agent": settings.user_agent, **(headers or {})}
    tmp = Path(tempfile.mkstemp(prefix="gwmi_")[1])
    with httpx.Client(timeout=settings.http_timeout, follow_redirects=True, headers=h) as c:
        with c.stream("GET", url, params=params) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_bytes(1 << 20):
                    f.write(chunk)
            return tmp, r.status_code


# ----------------------------------------------------------------------
# Execução
# ----------------------------------------------------------------------
@dataclass
class RunContext:
    db: Database
    settings: Settings
    run_id: int
    source_id: str
    raw: RawStore
    ingestions: list[dict] = field(default_factory=list)

    def register_raw(self, uri: str, local: Path, http_status: int | None = None,
                     meta: dict | None = None, name: str | None = None) -> Path:
        stored, sha, size = self.raw.put_file(self.source_id, Path(local), name)
        self.db.execute(
            """INSERT INTO raw.ingestion (run_id, source_id, uri, storage_path, content_sha256, bytes, http_status, meta)
               VALUES (%(r)s, %(s)s, %(u)s, %(p)s, %(h)s, %(b)s, %(st)s, %(m)s::jsonb)""",
            {"r": self.run_id, "s": self.source_id, "u": uri, "p": str(stored), "h": sha, "b": size,
             "st": http_status, "m": json.dumps(meta or {})})
        self.ingestions.append({"uri": uri, "path": str(stored), "sha256": sha, "bytes": size})
        return stored


@dataclass
class RunReport:
    run_id: int
    job: str
    status: str
    staged: int = 0
    rejected: int = 0
    inserted: int = 0
    revised: int = 0
    unchanged: int = 0
    retired: int = 0
    dq: list[dict] = field(default_factory=list)
    error: str | None = None

    def summary(self) -> str:
        dq_fail = [d["rule_id"] for d in self.dq if not d["passed"]]
        return (f"run {self.run_id} [{self.job}] {self.status}: staged={self.staged} rejected={self.rejected} "
                f"inserted={self.inserted} revised={self.revised} unchanged={self.unchanged} retired={self.retired}"
                + (f" · DQ alertas: {', '.join(dq_fail)}" if dq_fail else "")
                + (f" · erro: {self.error}" if self.error else ""))


class Job:
    """Subclasses definem source_id, job_name, dataset e implementam fetch() + rows()."""
    source_id: str = ""
    job_name: str = ""
    dataset: str = "series"            # 'trade' | 'series'
    is_simulated: bool = False

    def params(self) -> dict:
        return {}

    def fetch(self, ctx: RunContext) -> list[Path]:
        return []

    def rows(self, ctx: RunContext, files: list[Path]) -> Iterator[dict]:
        raise NotImplementedError

    def snapshot_scope(self):
        """(início, fim) quando o arquivo representa o recorte completo do período; senão None."""
        return None

    def after_merge(self, ctx: RunContext) -> None:
        """Gancho opcional (ex.: recalcular indicadores derivados)."""


def start_run(db: Database, source_id: str, job: str, params: dict, is_simulated: bool) -> int:
    return int(db.scalar(
        """INSERT INTO meta.etl_run (source_id, job, params, is_simulated)
           VALUES (%(s)s, %(j)s, %(p)s::jsonb, %(sim)s) RETURNING run_id""",
        {"s": source_id, "j": job, "p": json.dumps(params, default=str), "sim": is_simulated}))


def finish_run(db: Database, run_id: int, status: str, staged: int = 0, rejected: int = 0,
               error: str | None = None) -> None:
    db.execute(
        """UPDATE meta.etl_run SET status = %(st)s, finished_at = now(), rows_staged = %(n)s,
                  rows_rejected = %(rj)s, error = %(e)s WHERE run_id = %(r)s""",
        {"st": status, "n": staged, "rj": rejected, "e": error, "r": run_id})


def _batched(it: Iterable, n: int) -> Iterator[list]:
    it = iter(it)
    while batch := list(islice(it, n)):
        yield batch


def _to_trade_tuple(run_id: int, r: dict) -> tuple:
    return (run_id, r["flow"], r["period"], r["reporter_code"], r["partner_code"], r["code_scheme"], r["ncm8"],
            r.get("uf") or "--", int(r.get("urf_code") or 0), int(r.get("via_code") or 0), r["value_usd_fob"],
            r.get("value_freight_usd"), r.get("value_insurance_usd"), r.get("net_kg"), r.get("qty_stat"),
            r.get("stat_unit_code"))


def _to_series_tuple(run_id: int, r: dict) -> tuple:
    return (run_id, r["indicator_code"], r["geo_iso3"], r["period"], r.get("value"), r.get("obs_status", "A"))


def run_job(db: Database, job: Job, settings: Settings) -> RunReport:
    run_id = start_run(db, job.source_id, job.job_name, job.params(), job.is_simulated)
    ctx = RunContext(db, settings, run_id, job.source_id, RawStore(settings.raw_dir))
    rep = RunReport(run_id, job.job_name, "running")
    if job.dataset == "trade":
        table, cols, conv, validate, merge = "stg.trade", TRADE_COLUMNS, _to_trade_tuple, validate_trade_row, "dw.merge_trade"
    elif job.dataset == "series":
        table, cols, conv, validate, merge = "stg.series", SERIES_COLUMNS, _to_series_tuple, validate_series_row, "dw.merge_series"
    else:
        raise ValueError(f"dataset não suportado por run_job: {job.dataset}")
    try:
        files = job.fetch(ctx)
        rejected: list[tuple] = []

        def valid_rows() -> Iterator[tuple]:
            for r in job.rows(ctx, files):
                reason = validate(r)
                if reason:
                    rejected.append((run_id, job.dataset, reason, json.dumps(r, default=str)))
                    continue
                yield conv(run_id, r)

        for batch in _batched(valid_rows(), BATCH):
            rep.staged += db.copy_rows(table, cols, batch)
        if rejected:
            db.copy_rows("dq.rejected_row", ("run_id", "dataset", "reason", "row_data"), rejected)
        rep.rejected = len(rejected)

        scope = job.snapshot_scope() if job.dataset == "trade" else None
        if scope:
            res = db.query(f"SELECT * FROM {merge}(%(r)s, %(a)s::date, %(b)s::date)", {"r": run_id, "a": scope[0], "b": scope[1]})[0]
        else:
            res = db.query(f"SELECT * FROM {merge}(%(r)s)", {"r": run_id})[0]
        rep.inserted, rep.revised, rep.unchanged = int(res["inserted"]), int(res["revised"]), int(res["unchanged"])
        rep.retired = int(res.get("retired") or 0)
        job.after_merge(ctx)
        rep.dq = db.query("SELECT * FROM dq.run_checks(%(r)s, %(d)s)", {"r": run_id, "d": job.dataset})
        dq_errors = [d for d in rep.dq if not d["passed"] and d["severity"] == "error"]
        rep.status = "partial" if (rep.rejected or dq_errors) else "success"
        finish_run(db, run_id, rep.status, rep.staged, rep.rejected)
    except Exception as e:  # noqa: BLE001 — registrar qualquer falha no run
        rep.status, rep.error = "failed", f"{type(e).__name__}: {e}"
        log.exception("falha no run %s", run_id)
        try:
            db.execute(f"DELETE FROM {table} WHERE run_id = %(r)s", {"r": run_id})
        finally:
            finish_run(db, run_id, "failed", rep.staged, rep.rejected, rep.error)
    return rep


def month_start(y: int, m: int) -> date:
    return date(int(y), int(m), 1)


def parse_decimal(s: Any) -> float | None:
    """Aceita '1.234,56', '1234.56', '', '-', '..', '...', 'X' (sigilo), '.' (FRED)."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    t = str(s).strip().strip('"')
    if t in ("", "-", "..", "...", "X", ".", "NA", "null", "None"):
        return None
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".")
    elif "," in t:
        t = t.replace(",", ".")
    return float(t)
