"""Chave de acesso da API.

GWMI_API_KEYS  = chaves aceitas, separadas por vírgula (cada uma com 32+ caracteres).
GWMI_OPEN_READ = "1" libera leitura (GET) sem chave; escrita continua exigindo chave.

Sem nenhuma chave configurada, a API recusa tudo (falha fechada): um servidor recém-criado
sem a variável não fica aberto por engano. A chave vem no cabeçalho `X-API-Key`
ou em `Authorization: Bearer <chave>`; nunca na URL (URLs vão para logs e histórico).
"""
from __future__ import annotations

import hmac
import os

from fastapi import HTTPException, Request

MIN_LEN = 32


def _keys() -> list[str]:
    raw = os.environ.get("GWMI_API_KEYS", "")
    return [k.strip() for k in raw.split(",") if len(k.strip()) >= MIN_LEN]


def _presented(request: Request) -> str | None:
    k = request.headers.get("x-api-key")
    if k:
        return k.strip()
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def check_key(presented: str | None, keys: list[str]) -> bool:
    if not presented:
        return False
    ok = False
    for k in keys:  # compara com todas, em tempo constante
        ok |= hmac.compare_digest(presented.encode(), k.encode())
    return ok


def require_key(request: Request) -> None:
    if request.method == "OPTIONS":
        return
    if request.method == "GET" and os.environ.get("GWMI_OPEN_READ") == "1":
        return
    keys = _keys()
    if not keys:
        raise HTTPException(503, "API sem chave configurada (GWMI_API_KEYS). Acesso bloqueado por segurança.")
    if not check_key(_presented(request), keys):
        raise HTTPException(401, "Chave de acesso ausente ou inválida. Envie no cabeçalho X-API-Key.",
                            headers={"WWW-Authenticate": "Bearer"})
