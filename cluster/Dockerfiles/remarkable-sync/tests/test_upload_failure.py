"""Tests for sync.py's handling of a failing `rmapi put`: one failure must
not abort the cycle, and log wording must not drift from
loki-rules-remarkable-sync.yaml's alert query.
"""

import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import sync  # noqa: E402

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
FAILING = "hallelujah.ultimatetab.json"
GOOD = "heyjude.ultimatetab.json"


@pytest.fixture
def tab_dir(tmp_path, monkeypatch):
    tabs = tmp_path / "saved-tabs"
    tabs.mkdir()
    for name in (FAILING, GOOD):
        shutil.copy(FIXTURES_DIR / name, tabs / name)
    monkeypatch.setattr(sync, "TAB_DIR", tabs)
    monkeypatch.setattr(sync, "STATE_DIR", tabs / ".remarkable-sync-state")
    monkeypatch.setattr(sync, "HEARTBEAT_FILE", tmp_path / "heartbeat")
    return tabs


def fail_uploads_for(monkeypatch, *tab_names):
    """Fail `rmapi put` for the named tabs; succeed for the rest."""
    failing = {Path(name).stem for name in tab_names}
    attempted = []

    def fake_run(cmd, **kwargs):
        pdf = Path(cmd[2])
        attempted.append(pdf.stem)
        if pdf.stem in failing:
            raise subprocess.CalledProcessError(
                1,
                cmd,
                output=f"uploading: [{pdf}]...",
                stderr=(
                    f"ERROR: main.go:86: Error:  failed to upload file [{pdf}] "
                    "request failed with status 400\n"
                ),
            )
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(sync.subprocess, "run", fake_run)
    return attempted


def test_failed_upload_does_not_abort_the_cycle(tab_dir, monkeypatch):
    fail_uploads_for(monkeypatch, FAILING)
    sync.run_cycle()
    assert sync.marker_for(tab_dir / GOOD).exists()


def test_failed_upload_leaves_no_markers(tab_dir, monkeypatch):
    fail_uploads_for(monkeypatch, FAILING)
    sync.run_cycle()
    assert not sync.marker_for(tab_dir / FAILING).exists()
    assert not sync.failed_marker_for(tab_dir / FAILING).exists()


def test_heartbeat_is_touched_when_every_upload_fails(tab_dir, monkeypatch):
    fail_uploads_for(monkeypatch, FAILING, GOOD)
    sync.run_cycle()
    assert sync.HEARTBEAT_FILE.exists()


def test_failed_upload_retries_on_the_next_cycle(tab_dir, monkeypatch):
    fail_uploads_for(monkeypatch, FAILING)
    sync.run_cycle()
    assert not sync.marker_for(tab_dir / FAILING).exists()

    attempted = fail_uploads_for(monkeypatch)
    sync.run_cycle()
    assert Path(FAILING).stem in attempted
    assert sync.marker_for(tab_dir / FAILING).exists()


def test_synced_tab_is_not_reuploaded(tab_dir, monkeypatch):
    fail_uploads_for(monkeypatch)
    sync.run_cycle()
    attempted = fail_uploads_for(monkeypatch)
    sync.run_cycle()
    assert attempted == []


def test_malformed_tab_is_retired_permanently(tab_dir, monkeypatch):
    """Regression guard: this stays .failed, unlike an upload error."""
    malformed = tab_dir / "malformed.ultimatetab.json"
    malformed.write_text(json.dumps({"tab": {"no_raw_tabs_here": True}}))
    fail_uploads_for(monkeypatch)
    sync.run_cycle()
    assert sync.failed_marker_for(malformed).exists()
    assert not sync.marker_for(malformed).exists()


def test_failure_log_matches_the_alert_query(tab_dir, monkeypatch, caplog):
    """Wording asserted here must match loki-rules-remarkable-sync.yaml."""
    fail_uploads_for(monkeypatch, FAILING)
    with caplog.at_level(logging.ERROR, logger="remarkable-sync"):
        sync.run_cycle()
    assert "rmapi put" in caplog.text
    assert "failed (exit" in caplog.text


def test_success_log_matches_the_alert_query(tab_dir, monkeypatch, caplog):
    fail_uploads_for(monkeypatch)
    with caplog.at_level(logging.INFO, logger="remarkable-sync"):
        sync.run_cycle()
    assert f"synced {GOOD}" in caplog.text
