import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_help_runs():
    result = subprocess.run(
        [sys.executable, "-m", "src.main", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--dry-run" in result.stdout
    assert "--scrape-only" in result.stdout
    assert "--no-ai" in result.stdout
    assert "--geo-backfill" in result.stdout
    assert "--cookie-cleanup" in result.stdout
    assert "--date-backfill" in result.stdout
    assert "--ticket-backfill" in result.stdout
    assert "--apply" in result.stdout


def test_missing_karakeep_is_config_error(monkeypatch):
    monkeypatch.delenv("KARAKEEP_URL", raising=False)
    monkeypatch.delenv("KARAKEEP_API_KEY", raising=False)
    monkeypatch.setattr("src.config.load_dotenv", lambda *_args, **_kwargs: False)
    monkeypatch.chdir(ROOT)
    from src.main import main

    assert main(["--log-level", "ERROR"]) == 2
    assert os.environ.get("KARAKEEP_API_KEY", "") == ""
