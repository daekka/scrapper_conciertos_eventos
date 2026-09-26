import logging
import os
import re
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from src.log_retention import (
    DEFAULT_CRON_LOG,
    DEFAULT_RETENTION_DAYS,
    prune_dated_log,
)


class _SecretFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        cleaned = re.sub(r"(Bearer\s+)\S+", r"\1***", message)
        cleaned = re.sub(r"(api[_-]?key[=:\s]+)\S+", r"\1***", cleaned, flags=re.I)
        if cleaned != message:
            record.msg = cleaned
            record.args = ()
        return True


def _cron_log_writable(path: Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            return os.access(path, os.W_OK)
        return os.access(path.parent, os.W_OK)
    except OSError:
        return False


def setup_logging(
    level: str,
    *,
    cron_log: Path | None = DEFAULT_CRON_LOG,
    retention_days: int = DEFAULT_RETENTION_DAYS,
) -> None:
    """Configura logging. En cron (stdout no-TTY y log escribible) rota a N días."""
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    root.addFilter(_SecretFilter())

    use_file = (
        cron_log is not None
        and not sys.stdout.isatty()
        and _cron_log_writable(cron_log)
    )
    if use_file:
        assert cron_log is not None
        prune_dated_log(cron_log, retention_days=retention_days)
        file_handler = TimedRotatingFileHandler(
            filename=str(cron_log),
            when="midnight",
            interval=1,
            backupCount=max(retention_days - 1, 1),
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    if sys.stdout.isatty() or not use_file:
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)
