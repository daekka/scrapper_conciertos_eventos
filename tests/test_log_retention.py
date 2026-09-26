from datetime import date
from pathlib import Path

import pytest

from src.log_retention import prune_dated_log


def test_prune_keeps_last_three_calendar_days(tmp_path: Path):
    log = tmp_path / "cron.log"
    log.write_text(
        "\n".join(
            [
                "2026-09-20 10:00:00,000 INFO old",
                "2026-09-23 10:00:00,000 INFO d1",
                "2026-09-24 10:00:00,000 INFO d2",
                "2026-09-25 10:00:00,000 INFO d3",
                "2026-09-26 10:00:00,000 INFO d4",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    dropped = prune_dated_log(log, retention_days=3, today=date(2026, 9, 26))
    text = log.read_text(encoding="utf-8")
    assert dropped == 2
    assert "2026-09-20" not in text
    assert "2026-09-23" not in text
    assert "2026-09-24" in text
    assert "2026-09-25" in text
    assert "2026-09-26" in text


def test_prune_noop_when_already_within_window(tmp_path: Path):
    log = tmp_path / "cron.log"
    content = "2026-09-25 01:00:00,000 INFO a\n2026-09-26 01:00:00,000 INFO b\n"
    log.write_text(content, encoding="utf-8")
    assert prune_dated_log(log, retention_days=3, today=date(2026, 9, 26)) == 0
    assert log.read_text(encoding="utf-8") == content


def test_prune_missing_file_returns_zero(tmp_path: Path):
    assert prune_dated_log(tmp_path / "missing.log", retention_days=3) == 0


def test_prune_rejects_invalid_retention(tmp_path: Path):
    with pytest.raises(ValueError):
        prune_dated_log(tmp_path / "x.log", retention_days=0)
