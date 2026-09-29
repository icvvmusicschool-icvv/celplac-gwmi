from __future__ import annotations

from datetime import date

from fastapi import Request

from .db import Repo


def get_repo(request: Request) -> Repo:
    return request.app.state.repo


def months_ago(n: int, ref: date | None = None) -> date:
    ref = ref or date.today()
    y, m = ref.year, ref.month - n
    while m <= 0:
        y, m = y - 1, m + 12
    return date(y, m, 1)
