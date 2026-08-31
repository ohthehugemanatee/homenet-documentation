"""Tests for how the sync loop behaves when `rmapi put` fails.

Written against the reMarkable outage that motivated them: from 2026-08-17
every upload returned HTTP 400 (ddvk/rmapi#76 - the server began rejecting
an unsorted root index, fixed upstream in v0.0.35). For 13 days the pod
stayed 2/2 Running while nothing reached the tablet.

Two things are pinned here:

1. The loop degrades gracefully. One tab's upload failing must not abort the
   cycle, must not mark that tab permanently failed, and must not stop the
   heartbeat - a container that keeps processing its queue is healthy even
   when every item in the queue fails. Only the workload failed.

2. The log wording the alert matches on. `RemarkableSyncUploadsFailing`
   (cluster/services/loki-rules-remarkable-sync.yaml) is a Loki rule keyed to
   the literal strings "rmapi put" / "failed (exit" and "synced ", which makes
   those strings an interface. Reword them and the alert silently stops firing,
   which is the exact failure mode that let this outage run for 13 days. These
   assertions are what makes that a test failure instead.
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
    """A TAB_DIR holding one tab whose upload will fail and one that works.

    sync.py resolves TAB_DIR/STATE_DIR/HEARTBEAT_FILE from the environment at
    import time, so redirect the module attributes rather than the env vars.
    """
    tabs = tmp_path / "saved-tabs"
    tabs.mkdir()
    for name in (FAILING, GOOD):
        shutil.copy(FIXTURES_DIR / name, tabs / name)
    monkeypatch.setattr(sync, "TAB_DIR", tabs)
    monkeypatch.setattr(sync, "STATE_DIR", tabs / ".remarkable-sync-state")
    monkeypatch.setattr(sync, "HEARTBEAT_FILE", tmp_path / "heartbeat")
    return tabs


def fail_uploads_for(monkeypatch, *tab_names):
    """Make `rmapi put` exit 1 for the named tabs, succeed for the rest.

    Reproduces a real 400 as CalledProcessError with rmapi's own stdout and
    stderr attached, so upload_to_remarkable's error handling runs for real
    instead of being stubbed past. Returns the list of uploaded PDF stems so a
    test can assert on what was actually attempted.
    """
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
    """The failing tab sorts first, so a cycle that aborted on it would leave
    the good tab untouched. Guards the whole queue against one bad item."""
    fail_uploads_for(monkeypatch, FAILING)
    sync.run_cycle()
    assert sync.marker_for(tab_dir / GOOD).exists()


def test_failed_upload_leaves_no_markers(tab_dir, monkeypatch):
    """No .synced (it did not sync) and no .failed (upload errors are
    transient - a paired-token expiry or an API outage must not permanently
    retire a tab). Absent markers are what make it retry next cycle."""
    fail_uploads_for(monkeypatch, FAILING)
    sync.run_cycle()
    assert not sync.marker_for(tab_dir / FAILING).exists()
    assert not sync.failed_marker_for(tab_dir / FAILING).exists()


def test_heartbeat_is_touched_when_every_upload_fails(tab_dir, monkeypatch):
    """The probes read this file. A container still working its queue is live
    and ready even when nothing in the queue succeeds - surfacing the workload
    failure is the alert's job, not the probe's."""
    fail_uploads_for(monkeypatch, FAILING, GOOD)
    sync.run_cycle()
    assert sync.HEARTBEAT_FILE.exists()


def test_failed_upload_retries_on_the_next_cycle(tab_dir, monkeypatch):
    """The 13-day backlog has to drain by itself once the cause is fixed."""
    fail_uploads_for(monkeypatch, FAILING)
    sync.run_cycle()
    assert not sync.marker_for(tab_dir / FAILING).exists()

    attempted = fail_uploads_for(monkeypatch)  # nothing fails now
    sync.run_cycle()
    assert Path(FAILING).stem in attempted
    assert sync.marker_for(tab_dir / FAILING).exists()


def test_synced_tab_is_not_reuploaded(tab_dir, monkeypatch):
    """The .synced marker is the only thing standing between a recovered
    outage and a duplicate of every tab on the tablet."""
    fail_uploads_for(monkeypatch)
    sync.run_cycle()
    attempted = fail_uploads_for(monkeypatch)
    sync.run_cycle()
    assert attempted == []


def test_malformed_tab_is_retired_permanently(tab_dir, monkeypatch):
    """The one case that IS given up on: JSON that parses but has no
    tab.raw_tabs will never parse differently, so it gets a .failed marker.
    Regression guard - this must not be widened to cover upload errors."""
    malformed = tab_dir / "malformed.ultimatetab.json"
    malformed.write_text(json.dumps({"tab": {"no_raw_tabs_here": True}}))
    fail_uploads_for(monkeypatch)
    sync.run_cycle()
    assert sync.failed_marker_for(malformed).exists()
    assert not sync.marker_for(malformed).exists()


def test_failure_log_matches_the_alert_query(tab_dir, monkeypatch, caplog):
    """Pins the strings loki-rules-remarkable-sync.yaml greps for. Changing
    this wording without changing the rule disables the alert silently."""
    fail_uploads_for(monkeypatch, FAILING)
    with caplog.at_level(logging.ERROR, logger="remarkable-sync"):
        sync.run_cycle()
    assert "rmapi put" in caplog.text
    assert "failed (exit" in caplog.text


def test_success_log_matches_the_alert_query(tab_dir, monkeypatch, caplog):
    """The alert stays quiet while tabs are getting through, so the rule
    depends on this wording as much as on the failure wording."""
    fail_uploads_for(monkeypatch)
    with caplog.at_level(logging.INFO, logger="remarkable-sync"):
        sync.run_cycle()
    assert f"synced {GOOD}" in caplog.text
