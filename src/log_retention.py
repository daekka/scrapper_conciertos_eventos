"""Retención del log de cron: solo los últimos N días de calendario."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from src.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

DEFAULT_CRON_LOG = PROJECT_ROOT / "logs" / "cron.log"
DEFAULT_RETENTION_DAYS = 3


def prune_dated_log(
    path: Path,
    *,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    today: date | None = None,
    timezone: str = "Europe/Madrid",
) -> int:
    """Reescribe ``path`` dejando solo líneas con fecha >= hoy-(N-1).

    Las líneas deben empezar por ``YYYY-MM-DD`` (formato del logging estándar).
    Las líneas sin fecha se conservan solo si ya hay alguna línea retenida.
    Devuelve cuántas líneas se eliminaron. Si no puede leer/escribir, devuelve 0.
    """
    if retention_days < 1:
        raise ValueError("retention_days debe ser >= 1")
    if not path.is_file():
        return 0

    if today is None:
        today = datetime.now(ZoneInfo(timezone)).date()
    cutoff = (today - timedelta(days=retention_days - 1)).isoformat()

    try:
        original = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0

    kept: list[str] = []
    dropped = 0
    for line in original.splitlines(keepends=True):
        prefix = line[:10]
        if len(prefix) == 10 and prefix[4] == "-" and prefix[7] == "-" and prefix[:4].isdigit():
            if prefix >= cutoff:
                kept.append(line)
            else:
                dropped += 1
        elif kept:
            kept.append(line)
        else:
            dropped += 1

    new_text = "".join(kept)
    if new_text == original:
        return 0

    try:
        path.write_text(new_text, encoding="utf-8")
    except OSError:
        return 0
    return dropped
