"""Atualização automática: consulta todas as fontes, carrega o que mudou e recalcula o resto.

Pensado para rodar uma vez por dia (GitHub Actions). Cada fonte roda isolada: a falha de uma
não impede as outras. Arquivo idêntico ao da última carga vira execução 'unchanged' (nada é
reprocessado). Fontes pesadas ou de publicação rara têm dia certo para rodar, salvo --force.

Ordem: fontes → derivados (só os afetados) → sinais (referência = 1º dia do mês corrente) → qualidade.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable

from .config import Settings
from .db import Database
from .pipeline import Job, RunReport, run_job

# (série FRED, indicador, geo, início) — mesmos endereços das cargas anteriores
FRED_SET = (
    ("HOUST", "US_HOUSING_STARTS", "USA", "2000-01-01"),
    ("HOUST1F", "US_HOUSING_STARTS_1F", "USA", "2000-01-01"),
    ("PERMIT", "US_BUILDING_PERMITS", "USA", "2000-01-01"),
    ("DEXMXUS", "FX_USD_MXN", "MEX", "2021-01-01"),
    ("DEXCHUS", "FX_USD_CNY", "CHN", "2021-01-01"),
    ("PCU483111483111", "FREIGHT_PPI_DEEPSEA_US", "USA", "2016-01-01"),
    ("PCU3252113252114", "RESIN_PPI_THERMOSET_US", "USA", "2016-01-01"),
    ("WPU083103", "US_PPI_SOFTWOOD_PLYWOOD", "USA", "2016-01-01"),
    ("DCOILBRENTEU", "BRENT", "WLD", "2021-01-01"),
)
GROUPS = ("comex", "ptax", "fred", "macro", "ibge", "comtrade")


@dataclass
class Step:
    group: str
    label: str
    make: Callable[[], Job | None]
    derive: tuple[str, ...] = ()


@dataclass
class Outcome:
    group: str
    label: str
    status: str
    report: RunReport | None = None
    error: str | None = None
    seconds: float = 0.0


@dataclass
class Summary:
    outcomes: list[Outcome] = field(default_factory=list)
    derived: list[dict] = field(default_factory=list)
    signals: list[dict] = field(default_factory=list)
    dq: list[dict] = field(default_factory=list)

    @property
    def failed(self) -> list[Outcome]:
        return [o for o in self.outcomes if o.status == "failed"]

    def markdown(self) -> str:
        icon = {"success": "✅", "partial": "⚠️", "unchanged": "▫️", "failed": "❌", "skipped": "⏭️"}
        lines = ["## Atualização de dados — CELPLAC GWMI", "",
                 "| | Fonte | Situação | Inseridas | Revisadas | Run | Observação |", "|---|---|---|---:|---:|---:|---|"]
        for o in self.outcomes:
            r = o.report
            lines.append(f"| {icon.get(o.status, '')} | {o.label} | {o.status} | {r.inserted if r else ''} | "
                         f"{r.revised if r else ''} | {r.run_id if r else ''} | {(o.error or '')[:160]} |")
        if self.derived:
            lines += ["", "**Derivados recalculados:** " + ", ".join(
                f"{d['group']} (+{d.get('inserted', 0)}/~{d.get('revised', 0)})" for d in self.derived)]
        if self.signals:
            fired = [s for s in self.signals if s["result"] in ("SINAL", "INDICAÇÃO")]
            lines += ["", f"**Sinais:** {len(self.signals)} avaliados; "
                      + ("disparados: " + ", ".join(f"{s['rule']} {s['market']} = {s['result']}" for s in fired) if fired
                         else "nenhum sinal ou indicação.")]
        if self.dq:
            bad = [d for d in self.dq if not d["passed"]]
            lines += ["", "**Qualidade:** " + (", ".join(f"{d['rule_id']} ({d['failing']})" for d in bad) if bad
                                               else "todas as regras passaram.")]
        return "\n".join(lines) + "\n"


def _months_back(n: int, ref: date) -> list[str]:
    y, m, out = ref.year, ref.month, []
    for _ in range(n):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append(f"{y}{m:02d}")
    return sorted(out)


def plan(today: date, force: bool = False) -> list[Step]:
    """Monta a lista de passos do dia."""
    from .connectors import open_sources as osrc
    from .connectors.comexstat import ComexTradeJob
    from .connectors.comtrade import MARKETS, ComtradePreviewJob
    from .connectors.series_sources import PIM_WOOD, FredJob, PevsJob, PtaxJob, SidraJob

    monday = today.weekday() == 0
    first_monday = monday and today.day <= 7
    steps: list[Step] = []

    # Comex Stat: ano corrente; no 1º trimestre também o anterior (fechamento e revisões)
    years = [today.year] + ([today.year - 1] if today.month <= 3 else [])
    for y in years:
        steps.append(Step("comex", f"Comex Stat exportações {y}", lambda y=y: ComexTradeJob("X", y), ("br_exports",)))

    # PTAX: últimos 15 dias (o merge ignora o que já existe)
    for cur in ("USD", "EUR", "GBP"):
        steps.append(Step("ptax", f"PTAX {cur}", lambda cur=cur: PtaxJob(cur, today - timedelta(days=15), today), ("fx_cross",)))

    for sid, ind, geo, st in FRED_SET:
        steps.append(Step("fred", f"FRED {sid}", lambda sid=sid, ind=ind, geo=geo, st=st:
                          FredJob(sid, ind, geo, date.fromisoformat(st)),
                          ("fx_cross",) if sid.startswith("DEX") else ()))

    labels = ("FRED INDPRO a/a", "FRED TTLCONS a/a", "Eurostat produção industrial UE", "Eurostat construção UE",
              "NBS China produção industrial", "INDEC IPI Argentina", "INDEC ISAC Argentina")
    for lbl, mk in zip(labels, osrc.OPEN_JOBS[:7]):
        steps.append(Step("macro", lbl, mk))

    steps.append(Step("ibge", "IBGE IPP madeira", osrc.OPEN_JOBS[7]))
    steps.append(Step("ibge", "IBGE PIM-PF madeira", lambda: SidraJob(PIM_WOOD["path"], PIM_WOOD["indicator"], PIM_WOOD["match"])))
    if monday or force:  # PEVS é anual: verificar uma vez por semana basta
        steps.append(Step("ibge", "IBGE PEVS silvicultura", lambda: PevsJob()))
        steps.append(Step("ibge", "IBGE PEVS preço implícito", lambda: osrc.PevsPriceJob()))

    if monday or force:  # Comtrade: limite de ~1 consulta/s; os países reportam com atraso
        for p in _months_back(14, today):
            steps.append(Step("comtrade", f"Comtrade importações 4412 {p}",
                              lambda p=p: ComtradePreviewJob("4412", "M", p, freq="M", partner="0,76", only=MARKETS),
                              ("market_imports",)))
    if first_monday or force:  # concorrentes anuais: os dois últimos anos fechados
        for cmd in ("4412", "4408", "4407"):
            for y in (today.year - 2, today.year - 1):
                steps.append(Step("comtrade", f"Comtrade concorrentes {cmd} {y}",
                                  lambda cmd=cmd, y=y: ComtradePreviewJob(cmd, "X", str(y), freq="A", partner="0")))
    return steps


def run_update(db: Database, settings: Settings, today: date | None = None, only: tuple[str, ...] = (),
               force: bool = False, echo: Callable[[str], None] = print) -> Summary:
    from .jobs import run_derive, run_signals

    today = today or date.today()
    summ = Summary()
    to_derive: set[str] = set()
    changed = False
    for st in plan(today, force):
        if only and st.group not in only:
            continue
        t0 = time.time()
        try:
            rep = run_job(db, st.make(), settings)
            o = Outcome(st.group, st.label, rep.status, rep, rep.error)
        except Exception as e:  # noqa: BLE001 — falha antes de abrir o run (ex.: rede)
            o = Outcome(st.group, st.label, "failed", None, f"{type(e).__name__}: {e}")
        o.seconds = time.time() - t0
        summ.outcomes.append(o)
        echo(f"{o.status:<9} {st.label}" + (f" — {o.error}" if o.error else "")
             + (f" (+{o.report.inserted} ~{o.report.revised})" if o.report and o.status in ("success", "partial") else ""))
        if o.status in ("success", "partial") and o.report and (o.report.inserted or o.report.revised or o.report.retired):
            changed = True
            to_derive.update(st.derive)
        if st.group == "comtrade":
            time.sleep(1.5)  # limite da API pública

    for g in ("br_exports", "market_imports", "fx_cross"):
        if g in to_derive or (force and not only):
            try:
                d = run_derive(db, g)
                summ.derived.append(d)
                echo(f"derivado  {g}: +{d.get('inserted')} ~{d.get('revised')}")
            except Exception as e:  # noqa: BLE001
                summ.outcomes.append(Outcome("derive", f"Derivado {g}", "failed", None, f"{type(e).__name__}: {e}"))

    if changed or force:
        try:
            summ.signals = run_signals(db, today.replace(day=1))
        except Exception as e:  # noqa: BLE001
            summ.outcomes.append(Outcome("signals", "Sinais", "failed", None, f"{type(e).__name__}: {e}"))
    try:
        summ.dq = db.query("SELECT * FROM dq.run_checks()")
    except Exception as e:  # noqa: BLE001
        summ.outcomes.append(Outcome("dq", "Qualidade de dados", "failed", None, f"{type(e).__name__}: {e}"))

    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(summ.markdown())
    return summ
