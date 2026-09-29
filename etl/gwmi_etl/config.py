from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    return v if v not in (None, "") else default


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", "postgresql://gwmi:gwmi@localhost:5432/gwmi"))
    raw_dir: Path = field(default_factory=lambda: Path(_env("GWMI_RAW_DIR", "./data/raw")))
    http_timeout: float = field(default_factory=lambda: float(_env("GWMI_HTTP_TIMEOUT", "120")))
    user_agent: str = "CELPLAC-GWMI-ETL/0.2 (+market intelligence; contato interno)"

    # Comex Stat — arquivos em lote e tabelas auxiliares (verificar URLs vigentes no portal)
    comex_bulk_url: str = field(default_factory=lambda: _env(
        "COMEX_BULK_URL", "https://balanca.mdic.gov.br/balanca/bd/comexstat-bd/ncm/{flow}_{year}.csv"))
    comex_tables_url: str = field(default_factory=lambda: _env(
        "COMEX_TABLES_URL", "https://balanca.mdic.gov.br/balanca/bd/tabelas/{table}.csv"))
    # Capítulo 44 — recorte monitorado (SH4)
    comex_hs4: tuple[str, ...] = ("4403", "4407", "4408", "4410", "4411", "4412")

    ptax_url: str = "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"
    sidra_url: str = "https://apisidra.ibge.gov.br/values"
    fred_url: str = "https://api.stlouisfed.org/fred/series/observations"
    fredgraph_url: str = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}&cosd={start}"
    fred_api_key: str | None = field(default_factory=lambda: _env("FRED_API_KEY"))
    comtrade_url: str = "https://comtradeapi.un.org/data/v1/get/C/{freq}/HS"
    comtrade_key: str | None = field(default_factory=lambda: _env("COMTRADE_API_KEY"))
    # API pública de pré-visualização (sem chave): 1 período por consulta, até 500 linhas
    comtrade_preview_url: str = "https://comtradeapi.un.org/public/v1/preview/C/{freq}/HS"
    comtrade_reporters_url: str = "https://comtradeapi.un.org/files/v1/app/reference/Reporters.json"


def settings() -> Settings:
    return Settings()
