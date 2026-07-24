"""Connector contract + a small run wrapper that writes fetch_log rows.

A connector implements `name`, `bucket`, and `fetch(ctx) -> ConnectorResult`. The orchestrator
(src/refresh.py) calls `run()`, which times the connector, records provenance in fetch_log, and
never lets one connector's failure abort the whole refresh.
"""
from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .. import models


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Context:
    cfg: object          # config.Config
    conn: object         # sqlite3.Connection
    client: object       # http.Client
    force: bool = False
    year: int | None = None
    states: list[str] = field(default_factory=list)


@dataclass
class ConnectorResult:
    aips: list[models.AIP] = field(default_factory=list)
    products: list[models.Product] = field(default_factory=list)
    # Free-form coverage notes surfaced in the final report (e.g. "IA: 3 filings; TX: pending").
    coverage: list[str] = field(default_factory=list)
    status: str = "ok"
    http_status: int | None = None
    message: str | None = None


class Connector:
    name: str = "base"
    bucket: str = ""      # informational: which product bucket this feeds

    def fetch(self, ctx: Context) -> ConnectorResult:  # pragma: no cover - abstract
        raise NotImplementedError

    # -- orchestration ----------------------------------------------------
    def run(self, ctx: Context) -> ConnectorResult:
        started = _now_iso()
        try:
            result = self.fetch(ctx)
        except Exception as exc:  # a broken connector must not kill the refresh
            result = ConnectorResult(status="error", message=f"{type(exc).__name__}: {exc}")
            result.coverage.append(f"{self.name}: ERROR {exc}")
            traceback.print_exc()

        n_written = 0
        for aip in result.aips:
            models.upsert_aip(ctx.conn, aip)
            n_written += 1
        for prod in result.products:
            models.upsert_product(ctx.conn, prod)
            n_written += 1
        ctx.conn.commit()

        ctx.conn.execute(
            """INSERT INTO fetch_log (source, target, status, http_status, rows, started_at,
                                      finished_at, message)
               VALUES (?,?,?,?,?,?,?,?)""",
            (self.name, ",".join(ctx.states) or None, result.status, result.http_status,
             n_written, started, _now_iso(), result.message),
        )
        ctx.conn.commit()
        return result
