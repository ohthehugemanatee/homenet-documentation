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
# white-space/overflow-wrap MUST be set on the `pre` selector itself, not
# `body`: <pre> has its own UA-stylesheet default of `white-space: pre`,
# which wins over an inherited value from `body` (a direct rule on the
# element beats inheritance regardless of stylesheet origin). Verified by
# rendering: with the rule on `body` only, an oversized line silently
# overflowed off the page edge and vanished instead of wrapping.
# overflow-wrap: anywhere is also required - tab lines are long unbroken
# runs of dashes/pipes with no whitespace, so `pre-wrap` alone has no wrap
# point to use and the line still overflows without it. It's a *fallback*
# though, not the primary wrap mechanism - see the WBR_AFTER_BAR note in
# convert_to_pdf() for why a plain forced break-all reads badly on tab
# notation specifically, and what actually supplies the preferred wrap
# points.
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
    overflow-wrap: anywhere;
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

STRING_LINE_RE = re.compile(r"^([A-Za-z0-9#]{1,3})\|")

# Empirically measured: the widest a line can be and still fit within a
# .tab-block's content area - the @page's content width minus that block's
# own border-left + padding-left - at the current 9pt font, without
# wrapping. Verified by rendering "e|" + N dashes + "|" inside the actual
# styled .tab-block and finding the exact N where it first wraps (73);
# deliberately NOT reusing the plain page-content-width figure (~76) from
# the font-size fix, since border/padding eat into it further for content
# specifically inside a .tab-block.
TAB_SYSTEM_MAX_WIDTH = 72

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


def _reflow_tab_block(tab_block_text: str, max_width: int = TAB_SYSTEM_MAX_WIDTH) -> str:
    """Re-lay-out a [tab]...[/tab] block's lines into "systems" (groups of
    whole measures) that each fit within max_width, instead of relying on
    each of the block's string-lines to wrap independently.

    Independent per-line wrapping (the previous approach, via <wbr> after
    every "|") is wrong for tab notation specifically: each string's line
    wraps at its OWN character count, so a wrapped continuation lands
    right after THAT string's own line - not grouped with the other
    strings' continuations for the same measures. Reported by the
    operator: a wrapped arpeggio's last measure showed up as one string's
    leftover fragment sandwiched between that string's own line and the
    next string's line, no longer vertically aligned with the other
    strings' matching measure - which defeats the entire point of tab
    notation (reading straight down at one horizontal position tells you
    what every string does at that instant).

    Splits each string's line into individual bar-terminated measures,
    packs whole measures (never splitting one) into systems that fit
    max_width, and re-emits the string's label on every system - the same
    way UG's own site handles an overlong tab line - so each system reads
    correctly on its own.

    Many real blocks lead with prose before the actual string lines - a
    chord-name header row, a "(fingerpick arpeggios)" note, etc. (UG
    includes this INSIDE the [tab]...[/tab] markers, not as separate
    text). That leading prose is passed through untouched - it isn't
    alignment-critical the way the string lines are - and only the
    trailing run of recognizable "<label>|..." lines gets reflowed.
    """
    lines = [
        line for line in tab_block_text.replace("\r\n", "\n").split("\n") if line.strip()
    ]
    first_string_line = next(
        (i for i, line in enumerate(lines) if STRING_LINE_RE.match(line)), None
    )
    if first_string_line is None:
        return tab_block_text  # no recognizable tab notation in this block at all

    prose_lines = lines[:first_string_line]
    string_lines = lines[first_string_line:]

    labels = []
    measures_per_line = []
    for line in string_lines:
        match = STRING_LINE_RE.match(line)
        if not match:
            # A non-string line shows up after the tab notation already
            # started (e.g. an inline comment mid-block) - too ambiguous
            # to reflow confidently. Leave the whole block untouched and
            # let the ordinary overflow-wrap fallback handle it.
            return tab_block_text
        label = match.group(1)
        measures = re.findall(r"[^|]*\|", line[match.end() :])
        labels.append(label)
        measures_per_line.append(measures)

    num_measures = len(measures_per_line[0])
    if num_measures == 0 or any(len(m) != num_measures for m in measures_per_line):
        return tab_block_text  # not uniformly barred across strings - don't guess

    label_width = max(len(label) for label in labels) + 1  # +1 for "|"
    measure_widths = [
        max(len(measures_per_line[s][i]) for s in range(len(labels)))
        for i in range(num_measures)
    ]

    systems = []
    start = 0
    width = label_width
    for i, measure_width in enumerate(measure_widths):
        if i > start and width + measure_width > max_width:
            systems.append((start, i))
            start = i
            width = label_width
        width += measure_width
    systems.append((start, num_measures))

    reflowed = "\n\n".join(
        "\n".join(
            f"{labels[s]}|" + "".join(measures_per_line[s][start:end])
            for s in range(len(labels))
        )
        for start, end in systems
    )
    if prose_lines:
        return "\n".join(prose_lines) + "\n" + reflowed
    return reflowed


def render_body_html(raw_tabs: str) -> str:
    """Turn UG's plain-text raw_tabs into the HTML fragment HTML_TEMPLATE
    embeds in its <pre>. Split out from convert_to_pdf so this markup
    transformation - the part that's had several rendering-fidelity bugs
    found in it - can be unit-tested directly against tricky real-world
    input without a full weasyprint render; see tests/test_convert.py.
    """
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
    raw_tabs = html.unescape(raw_tabs)
    # _reflow_tab_block() needs plain "<label>|<measure>|..." text to find
    # bar boundaries, so it runs on the unescaped source, before any HTML
    # markup is introduced. Each [tab]...[/tab] block gets re-laid-out into
    # width-fitting systems (see that function's docstring for why simple
    # per-line wrapping doesn't work for tab notation); blocks it declines
    # to touch (unrecognized shape) pass through unchanged, still covered
    # by the WBR_AFTER_BAR fallback below.
    raw_tabs = TAB_BLOCK_TAG.sub(
        lambda m: f"[tab]{_reflow_tab_block(m.group(1))}[/tab]", raw_tabs
    )
    # Escape, then turn UG's markup into real HTML tags on the now-safe
    # text - html.escape() doesn't touch `[`/`]`/letters, so the UG tag
    # regexes still match correctly afterward, and any stray `<`/`>`/`&`
    # in the source tab content is neutralized before we start inserting
    # real tags of our own.
    body = html.escape(raw_tabs)
    # WBR_AFTER_BAR: a `<wbr>` after every "|" gives the renderer a
    # preferred wrap point at each bar/measure boundary, as a fallback for
    # any content _reflow_tab_block() declined to reflow (unrecognized
    # shape) or non-tab prose that happens to contain "|". Without it, an
    # overlong line has no wrap opportunity at all - it's one unbroken run
    # of dashes - so overflow-wrap: anywhere's forced fallback break lands
    # wherever the character count runs out, typically mid-measure.
    # `<wbr>` is always preferred by the line-breaking algorithm over a
    # forced break. Harmless (a no-op) on already-reflowed tab-block
    # content, since that's now built to fit within TAB_SYSTEM_MAX_WIDTH
    # and shouldn't need to wrap at all.
    body = body.replace("|", "|<wbr>")
    body = TAB_BLOCK_TAG.sub(r'<span class="tab-block">\1</span>', body)
    body = CHORD_TAG.sub(r"<b>\1</b>", body)
    return body


def convert_to_pdf(tab_file: Path, out_pdf: Path) -> None:
    data = json.loads(tab_file.read_text())
    try:
        raw_tabs = data["tab"]["raw_tabs"]
    except (KeyError, TypeError) as exc:
        raise MalformedTabError(f"{tab_file.name}: {exc}") from exc
    body = render_body_html(raw_tabs)
    try:
        WeasyHTML(string=HTML_TEMPLATE.format(body=body)).write_pdf(str(out_pdf))
    except Exception:
        # weasyprint's own exceptions are normally descriptive, but log
        # explicitly here (rather than relying solely on run_cycle's outer
        # log.exception) so a PDF-generation failure is never silently
        # indistinguishable from an upload failure in the logs.
        log.error("weasyprint failed to render %s", tab_file.name)
        raise


def upload_to_remarkable(pdf_file: Path) -> None:
    try:
        subprocess.run(
            ["rmapi", "put", str(pdf_file), REMARKABLE_TARGET_FOLDER],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        # CalledProcessError's own __str__ is just "returned non-zero exit
        # status N" - it does NOT include stdout/stderr unless read off the
        # exception explicitly. That's exactly the unhelpful message seen
        # in the logs ("rmapi put call returned non-zero error code") with
        # no way to tell WHY (auth expired, folder missing, network error,
        # ...) without this.
        log.error(
            "rmapi put %s failed (exit %s): stdout=%r stderr=%r",
            pdf_file.name, exc.returncode, exc.stdout, exc.stderr,
        )
        raise


def sync_one(tab_file: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        pdf_file = Path(tmp) / f"{tab_file.stem}.pdf"
        log.info("converting %s", tab_file.name)
        convert_to_pdf(tab_file, pdf_file)
        # Logged before upload so a failure log always shows whether
        # conversion produced a real, non-empty file - the temp dir is
        # gone by the time anyone could otherwise check.
        log.info(
            "converted %s -> %d bytes", tab_file.name, pdf_file.stat().st_size
        )
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
