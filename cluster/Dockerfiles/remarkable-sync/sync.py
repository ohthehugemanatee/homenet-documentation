#!/usr/bin/env python3
"""Watches a SongHub saved-tabs directory and pushes new tabs to reMarkable Cloud."""

import html
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from weasyprint import HTML as WeasyHTML

TAB_DIR = Path(os.environ.get("TAB_DIR", "/app/saved-tabs"))
SYNC_INTERVAL_SECONDS = int(os.environ.get("SYNC_INTERVAL_SECONDS", "1800"))
REMARKABLE_TARGET_FOLDER = os.environ.get("REMARKABLE_TARGET_FOLDER", "SongHub")
HEARTBEAT_FILE = Path(os.environ.get("HEARTBEAT_FILE", "/tmp/heartbeat"))
STATE_DIR = TAB_DIR / ".remarkable-sync-state"

# Uses raw_tabs, NOT htmlTab: SongHub pre-wraps htmlTab's tab lines into
# short (~20-30 char) fragments for narrow mobile-width display, with string
# letters only labeled on each fragment's first line. Rendered at any real
# page width that just leaves the content stuck in the first few columns
# with blank space beyond it - not a layout bug on our end, a source-data
# choice. raw_tabs has full, un-chopped tab lines. It's plain text (not
# pre-escaped like htmlTab was), so it must be html.escape()'d before
# embedding. Portrait per operator request.
#
# white-space/word-break MUST be set on the `pre` selector itself, not
# `body`: <pre> has its own UA-stylesheet default of `white-space: pre`,
# which wins over an inherited value from `body` (a direct rule on the
# element beats inheritance regardless of stylesheet origin). Verified by
# rendering: with the rule on `body` only, an oversized line silently
# overflowed off the page edge and vanished instead of wrapping.
# word-break: break-all is also required - tab lines are long unbroken runs
# of dashes/pipes with no whitespace, so `pre-wrap` alone has no wrap point
# to use and the line still overflows without it.
#
# @page size is the reMarkable 2's ACTUAL physical screen size, not A4:
# 1404x1872px at 226 DPI = 157.79mm x 210.39mm (confirmed device spec).
# reMarkable has no in-app reflow/font-size control for PDFs, so the fixed
# size has to be right at generation time - and A4 (210mm wide) doesn't
# match the device's narrower 157.79mm screen. A4 content displayed on the
# device gets auto-scaled to fit-width, which was silently shrinking every
# font size by ~25% (157.79/210 = 0.751) below its nominal point size.
# Matching @page to the real screen means "8pt" actually renders as 8pt.
# font-size bumped 8pt -> 9pt on top of that fix: 9 / (8 * 0.751) = 1.50x
# the apparent size the operator was actually seeing before - the ~50%
# increase requested, landing almost exactly on that number once the A4
# mismatch is accounted for. Tradeoff, by the numbers: at 9pt with 6mm
# margins the content area is ~76 monospace characters wide (was ~105
# under the old oversized A4 virtual page), so busier tab passages wrap
# more often than before. This is a real, physical-width tradeoff, not a
# bug - the device is only so wide, and bigger text always means fewer
# characters fit per line.
#
# .tab-block gets break-inside/page-break-inside: avoid (both properties
# for engine compatibility - weasyprint honors the unprefixed Fragmentation
# name but the legacy one costs nothing to also set) because weasyprint's
# default pagination breaks between any two line boxes, including inside a
# six-line tab-block's own lines - reproduced empirically (a block that
# would otherwise straddle a page boundary got split 4 lines on one page,
# 2 on the next, exactly the reported "page break in the middle of a
# line/tab"). With the rule set, a block that doesn't fit in the remaining
# space on the current page moves to the next page as a whole instead.
HTML_TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  @page {{ size: 157.79mm 210.39mm; margin: 6mm; }}
  pre {{
    font-family: "DejaVu Sans Mono", monospace;
    font-size: 9pt;
    white-space: pre-wrap;
    word-break: break-all;
    margin: 0;
  }}
  .tab-block {{
    display: block;
    border-left: 2pt solid #999;
    padding-left: 4pt;
    margin: 2pt 0;
    break-inside: avoid;
    page-break-inside: avoid;
  }}
</style></head><body><pre>{body}</pre></body></html>
"""

# Ultimate Guitar's raw tab text wraps structural blocks in BBCode-style
# markers: [tab]...[/tab] around each six-line notation block, [ch]...[/ch]
# around inline chord names. UG's own site renderer uses these to typeset
# specially (chords bolded, tab set apart); we do the same instead of just
# discarding the markup, which would throw away real signal. Deliberately
# exact-word matches, NOT a generic `\[.*?\]` strip: real tab notation also
# uses brackets for artificial harmonics (e.g. a literal `[12]` on a string
# line, per the tab's own legend), which must NOT be touched.
#
# We looked at using an established UG-format converter (ChordSheetJS's
# UltimateGuitarParser, feeding the official chordpro CLI) instead of this
# regex approach, since that's the real "prefer established components"
# answer for chord-over-lyrics sheets. Verified empirically it does not fit
# here: that parser is built for UG's "Chords" page format and badly
# corrupts "Tabs"-type content like this (wraps string-letter tab lines
# e.g. `B|...` in ChordPro's [Chord] syntax, mangling them). ChordPro's own
# tab handling is just a verbatim monospace block (`{sot}`/`{eot}`) with no
# special typesetting anyway - the same treatment we already give tab
# blocks here, just via a much bigger Perl+Node toolchain for no gain on
# the part of the content that's actually tab notation.
TAB_BLOCK_TAG = re.compile(r"\[tab\](.*?)\[/tab\]", re.DOTALL)
CHORD_TAG = re.compile(r"\[ch\](.*?)\[/ch\]", re.DOTALL)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("remarkable-sync")


def marker_for(tab_file: Path) -> Path:
    return STATE_DIR / f"{tab_file.name}.synced"


def failed_marker_for(tab_file: Path) -> Path:
    return STATE_DIR / f"{tab_file.name}.failed"


class MalformedTabError(Exception):
    """Tab JSON parses but lacks the shape we expect - retrying won't help.

    Deliberately does NOT cover json.JSONDecodeError: invalid JSON syntax
    can mean SongHub wrote this file non-atomically and we read it mid-write,
    which is transient and should keep retrying next cycle. A KeyError/
    TypeError means the JSON parsed fine but the structure is simply wrong -
    that won't fix itself on retry.
    """


def convert_to_pdf(tab_file: Path, out_pdf: Path) -> None:
    data = json.loads(tab_file.read_text())
    try:
        raw_tabs = data["tab"]["raw_tabs"]
    except (KeyError, TypeError) as exc:
        raise MalformedTabError(f"{tab_file.name}: {exc}") from exc
    # unescape() before escape(): UG's own "Tablature Legend" footer text
    # (present verbatim in raw_tabs on many tabs) already comes
    # HTML-entity-encoded from their API - e.g. the literal 8 characters
    # "&lt;&gt;" for its "<>" volume-swell notation, not real "<"/">"
    # characters. Escaping that as-is double-encodes the leading "&" into
    # "&amp;", which the PDF's HTML parser then decodes exactly once back
    # to the literal text "&lt;&gt;" - not the intended "<>" - since entity
    # decoding doesn't recurse. unescape() first normalizes any such
    # pre-encoded entities (and no-ops on plain text, since a bare "&" not
    # part of a recognized entity is left alone), so every tab starts from
    # the same true-plain-text baseline before we escape it for real.
    #
    # Escape first, then turn UG's markup into real HTML tags on the
    # now-safe text - html.escape() doesn't touch `[`/`]`/letters, so the
    # UG tag regexes still match correctly afterward, and any stray
    # `<`/`>`/`&` in the source tab content is neutralized before we start
    # inserting real tags of our own.
    body = html.escape(html.unescape(raw_tabs))
    body = TAB_BLOCK_TAG.sub(r'<span class="tab-block">\1</span>', body)
    body = CHORD_TAG.sub(r"<b>\1</b>", body)
    WeasyHTML(string=HTML_TEMPLATE.format(body=body)).write_pdf(str(out_pdf))


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
        if marker_for(tab_file).exists() or failed_marker_for(tab_file).exists():
            continue
        try:
            sync_one(tab_file)
        except MalformedTabError:
            # Deterministic - the file itself is bad, retrying won't help.
            # Upload/network errors (rmapi not yet paired, transient outage)
            # deliberately fall through to the broad except below instead,
            # so those keep retrying rather than being given up on forever.
            failed_marker_for(tab_file).touch()
            log.exception("permanently skipping malformed tab %s", tab_file.name)
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
