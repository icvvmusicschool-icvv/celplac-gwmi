"""Comex Stat (MDIC/SECEX) — arquivos em lote por ano e tabelas auxiliares.

Formato dos arquivos em lote (EXP_AAAA.csv / IMP_AAAA.csv), separador ';':
  CO_ANO;CO_MES;CO_NCM;CO_UNID;CO_PAIS;SG_UF_NCM;CO_VIA;CO_URF;QT_ESTAT;KG_LIQUIDO;VL_FOB[;VL_FRETE;VL_SEGURO]
O arquivo anual tem todos os capítulos; filtramos o recorte monitorado (SH4)
em streaming, sem carregar o arquivo na memória.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Iterator

from ..pipeline import Job, RunContext, finish_run, http_download, month_start, parse_decimal, start_run, RawStore

FLOW_FILE = {"X": "EXP", "M": "IMP"}


def _open_text(path: Path) -> io.TextIOBase:
    raw = open(path, "rb")
    head = raw.read(65536)
    raw.seek(0)
    try:
        head.decode("utf-8")
        enc = "utf-8-sig"
    except UnicodeDecodeError:
        enc = "latin-1"
    return io.TextIOWrapper(raw, encoding=enc, newline="")


def parse_comex_trade(path: Path, flow: str, hs4: tuple[str, ...]) -> Iterator[dict]:
    with _open_text(path) as fh:
        rd = csv.DictReader(fh, delimiter=";")
        need = {"CO_ANO", "CO_MES", "CO_NCM", "CO_PAIS", "VL_FOB"}
        missing = need - set(rd.fieldnames or [])
        if missing:
            raise ValueError(f"arquivo Comex sem colunas esperadas: {sorted(missing)}")
        for r in rd:
            ncm = (r["CO_NCM"] or "").strip().zfill(8)
            if not ncm.startswith(hs4):
                continue
            yield {
                "flow": flow,
                "period": month_start(r["CO_ANO"], r["CO_MES"]),
                "reporter_code": "BRA",
                "partner_code": str(int(r["CO_PAIS"])),
                "code_scheme": "comex",
                "ncm8": ncm,
                "uf": (r.get("SG_UF_NCM") or "--").strip()[:2] or "--",
                "urf_code": int(r.get("CO_URF") or 0),
                "via_code": int(r.get("CO_VIA") or 0),
                "value_usd_fob": parse_decimal(r["VL_FOB"]),
                "value_freight_usd": parse_decimal(r.get("VL_FRETE")),
                "value_insurance_usd": parse_decimal(r.get("VL_SEGURO")),
                "net_kg": parse_decimal(r.get("KG_LIQUIDO")),
                "qty_stat": parse_decimal(r.get("QT_ESTAT")),
                "stat_unit_code": int(r["CO_UNID"]) if (r.get("CO_UNID") or "").strip() else None,
            }


class ComexTradeJob(Job):
    source_id = "comexstat"
    dataset = "trade"

    def __init__(self, flow: str, year: int, file: Path | None = None, hs4: tuple[str, ...] | None = None):
        assert flow in ("X", "M")
        self.flow, self.year, self.file = flow, int(year), Path(file) if file else None
        self.hs4 = hs4
        self.job_name = f"comexstat.{FLOW_FILE[flow].lower()}"

    def params(self):
        return {"flow": self.flow, "year": self.year, "file": str(self.file) if self.file else None}

    def snapshot_scope(self):
        """O arquivo anual é a verdade do ano: linhas ausentes são aposentadas no merge."""
        from datetime import date
        return date(self.year, 1, 1), date(self.year, 12, 1)

    def fetch(self, ctx: RunContext):
        name = f"{FLOW_FILE[self.flow]}_{self.year}.csv"
        if self.file:
            return [ctx.register_raw(f"file://{self.file.resolve()}", self.file, None, {"mode": "local"}, name)]
        url = ctx.settings.comex_bulk_url.format(flow=FLOW_FILE[self.flow], year=self.year)
        tmp, status = http_download(url, ctx.settings)
        try:
            return [ctx.register_raw(url, tmp, status, {"mode": "download"}, name)]
        finally:
            tmp.unlink(missing_ok=True)

    def rows(self, ctx, files):
        hs4 = self.hs4 or ctx.settings.comex_hs4
        for f in files:
            yield from parse_comex_trade(f, self.flow, tuple(hs4))


# ----------------------------------------------------------------------
# Tabelas auxiliares
# ----------------------------------------------------------------------
REF_TABLES = {
    # tabela: (kind, [colunas → c1..c4], alternativas de nome)
    "PAIS": ("pais", [("CO_PAIS",), ("CO_PAIS_ISOA3",), ("NO_PAIS",)]),
    "NCM_UNIDADE": ("unidade", [("CO_UNID",), ("NO_UNID",)]),
    "NCM": ("ncm", [("CO_NCM",), ("CO_UNID",), ("NO_NCM_POR", "NO_NCM")]),
    "URF": ("urf", [("CO_URF",), ("NO_URF",)]),
    "PAIS_BLOCO": ("bloco", [("CO_PAIS",), ("NO_BLOCO",)]),
}
# ordem importa: unidades antes de NCM
REF_ORDER = ("PAIS_BLOCO", "PAIS", "NCM_UNIDADE", "NCM", "URF")


def parse_ref_table(path: Path, table: str) -> Iterator[tuple]:
    kind, cols = REF_TABLES[table]
    with _open_text(path) as fh:
        rd = csv.DictReader(fh, delimiter=";")
        names = set(rd.fieldnames or [])
        chosen = []
        for alts in cols:
            hit = next((a for a in alts if a in names), None)
            if hit is None:
                raise ValueError(f"{table}.csv sem coluna {alts}")
            chosen.append(hit)
        for r in rd:
            vals = [(r.get(c) or "").strip() for c in chosen]
            if not vals[0]:
                continue
            yield (kind, *vals, *([None] * (4 - len(vals))))


def run_comex_reference(db, settings, files: dict[str, Path] | None = None) -> list[dict]:
    """Carrega PAIS, NCM_UNIDADE, NCM (cap. 44) e URF. `files` permite usar arquivos locais."""
    run_id = start_run(db, "comexstat", "comexstat.reference", {"local": bool(files)}, False)
    ctx = RunContext(db, settings, run_id, "comexstat", RawStore(settings.raw_dir))
    try:
        total = 0
        for t in REF_ORDER:
            if files and t in files and not Path(files[t]).exists():
                continue
            if files and t in files:
                p = ctx.register_raw(f"file://{Path(files[t]).resolve()}", Path(files[t]), None, {"table": t}, f"{t}.csv")
            elif files:
                continue
            else:
                url = settings.comex_tables_url.format(table=t)
                tmp, st = http_download(url, settings)
                try:
                    p = ctx.register_raw(url, tmp, st, {"table": t}, f"{t}.csv")
                finally:
                    tmp.unlink(missing_ok=True)
            rows = [(run_id, *r) for r in parse_ref_table(p, t)]
            total += db.copy_rows("stg.ref", ("run_id", "kind", "c1", "c2", "c3", "c4"), rows)
        res = db.query("SELECT * FROM dw.apply_comex_reference(%(r)s)", {"r": run_id})
        finish_run(db, run_id, "success", total, 0)
        return res
    except Exception as e:
        db.execute("DELETE FROM stg.ref WHERE run_id = %(r)s", {"r": run_id})
        finish_run(db, run_id, "failed", 0, 0, f"{type(e).__name__}: {e}")
        raise
