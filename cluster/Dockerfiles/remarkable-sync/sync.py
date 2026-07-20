#!/usr/bin/env python3
"""Watches a SongHub saved-tabs directory and pushes new tabs to reMarkable Cloud."""

import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from weasyprint import HTML

TAB_DIR = Path(os.environ.get("TAB_DIR", "/app/saved-tabs"))
SYNC_INTERVAL_SECONDS = int(os.environ.get("SYNC_INTERVAL_SECONDS", "1800"))
REMARKABLE_TARGET_FOLDER = os.environ.get("REMARKABLE_TARGET_FOLDER", "SongHub")
HEARTBEAT_FILE = Path(os.environ.get("HEARTBEAT_FILE", "/tmp/heartbeat"))
STATE_DIR = TAB_DIR / ".remarkable-sync-state"

# Wraps SongHub's already-<pre>-wrapped htmlTab field in a minimal document
# with a monospace font, so tab-line character alignment (string/bar
# positions) survives PDF rendering.
HTML_TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  @page {{ size: A4 landscape; margin: 1.5cm; }}
  body {{ font-family: "DejaVu Sans Mono", monospace; font-size: 8pt; white-space: pre-wrap; }}
</style></head><body>{body}</body></html>
"""

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("remarkable-sync")


def marker_for(tab_file: Path) -> Path:
    return STATE_DIR / f"{tab_file.name}.synced"


def convert_to_pdf(tab_file: Path, out_pdf: Path) -> None:
    data = json.loads(tab_file.read_text())
    html_tab = data["tab"]["htmlTab"]
    HTML(string=HTML_TEMPLATE.format(body=html_tab)).write_pdf(str(out_pdf))


def upload_to_remarkable(pdf_file: Path) -> None:
    subprocess.run(
        ["rmapi", "put", str(pdf_file), REMARKABLE_TARGET_FOLDER],
        check=True,
        capture_output=True,
        text=True,
    )


def sync_one(tab_file: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        pdf_file = Path(tmp) / f"{tab_file.stem}.pdf"
        convert_to_pdf(tab_file, pdf_file)
        upload_to_remarkable(pdf_file)
    marker_for(tab_file).touch()
    log.info("synced %s", tab_file.name)


def run_cycle() -> None:
    STATE_DIR.mkdir(exist_ok=True)
    for tab_file in sorted(TAB_DIR.glob("*.ultimatetab.json")):
        if marker_for(tab_file).exists():
            continue
        try:
            sync_one(tab_file)
        except Exception:
            log.exception("failed to sync %s, will retry next cycle", tab_file.name)
        # Touched after every file, not just at cycle end: a large first
        # batch (e.g. initial deploy) could otherwise take longer than the
        # liveness probe's startup grace, killing the container mid-upload
        # before any heartbeat was ever recorded.
        HEARTBEAT_FILE.touch()
    HEARTBEAT_FILE.touch()


def main() -> None:
    log.info(
        "starting: TAB_DIR=%s interval=%ss target_folder=%s",
        TAB_DIR, SYNC_INTERVAL_SECONDS, REMARKABLE_TARGET_FOLDER,
    )
    while True:
        run_cycle()
        time.sleep(SYNC_INTERVAL_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
