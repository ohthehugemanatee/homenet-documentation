"""Regression tests for sync.py's NewTabHandler (issue #179): a new
*.ultimatetab.json should trigger a sync cycle immediately instead of
waiting for the next periodic cycle.
"""

import sys
import threading
from pathlib import Path

from watchdog.events import FileCreatedEvent, FileMovedEvent

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import sync  # noqa: E402

DEBOUNCE = 0.05


def test_triggers_on_new_tab_file_created():
    triggered = threading.Event()
    handler = sync.NewTabHandler(on_new_tab=triggered.set, debounce_seconds=DEBOUNCE)
    handler.on_created(FileCreatedEvent("/tabs/foo.ultimatetab.json"))
    assert triggered.wait(timeout=1)


def test_triggers_on_new_tab_file_moved_into_place():
    """SongHub (or the filesystem) may write to a temp name and rename."""
    triggered = threading.Event()
    handler = sync.NewTabHandler(on_new_tab=triggered.set, debounce_seconds=DEBOUNCE)
    handler.on_moved(FileMovedEvent("/tabs/.tmp123", "/tabs/foo.ultimatetab.json"))
    assert triggered.wait(timeout=1)


def test_ignores_unrelated_files():
    triggered = threading.Event()
    handler = sync.NewTabHandler(on_new_tab=triggered.set, debounce_seconds=DEBOUNCE)
    handler.on_created(FileCreatedEvent("/tabs/foo.txt"))
    handler.on_created(FileCreatedEvent("/tabs/.remarkable-sync-state/foo.synced"))
    assert not triggered.wait(timeout=DEBOUNCE * 3)


def test_ignores_directories():
    triggered = threading.Event()
    handler = sync.NewTabHandler(on_new_tab=triggered.set, debounce_seconds=DEBOUNCE)
    event = FileCreatedEvent("/tabs/some.ultimatetab.json")
    event.is_directory = True
    handler.on_created(event)
    assert not triggered.wait(timeout=DEBOUNCE * 3)


def test_debounces_bursts_into_one_trigger():
    calls = []
    handler = sync.NewTabHandler(
        on_new_tab=lambda: calls.append(1), debounce_seconds=DEBOUNCE
    )
    for i in range(5):
        handler.on_created(FileCreatedEvent(f"/tabs/{i}.ultimatetab.json"))
    # Give the debounce timer time to fire exactly once.
    threading.Event().wait(DEBOUNCE * 4)
    assert calls == [1]
