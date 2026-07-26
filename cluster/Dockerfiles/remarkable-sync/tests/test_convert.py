"""Regression tests for sync.py's raw_tabs -> PDF conversion.

Fixtures under tests/fixtures/ are real SongHub-downloaded
*.ultimatetab.json files, kept specifically for the rendering edge cases
they were used to find and fix: multi-measure single lines that need
wrapping (Hallelujah, Somewhere Over The Rainbow), pre-HTML-escaped
legend text (Blue Moon), thumb/finger notation and inline
timestamps/time-signatures (Classical Gas), and dense sequential tab
blocks (Hey Jude). When a new rendering bug is found and fixed, add (or
extend) a fixture and an assertion here instead of relying on manual
re-inspection to catch a future regression.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import sync  # noqa: E402

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
FIXTURE_FILES = sorted(FIXTURES_DIR.glob("*.ultimatetab.json"))
STRING_LINE = re.compile(r"^[A-Za-z0-9#]{0,3}\|")


def _compact(text: str) -> str:
    return "".join(text.split())


def _render(tab_file: Path, tmp_path: Path) -> Path:
    out_pdf = tmp_path / f"{tab_file.stem}.pdf"
    sync.convert_to_pdf(tab_file, out_pdf)
    return out_pdf


def _pdftotext_pages(pdf_file: Path) -> list:
    out = subprocess.run(
        ["pdftotext", "-layout", str(pdf_file), "-"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return out.split("\x0c")


@pytest.mark.parametrize("tab_file", FIXTURE_FILES, ids=lambda p: p.stem)
def test_conversion_succeeds(tab_file, tmp_path):
    out_pdf = _render(tab_file, tmp_path)
    assert out_pdf.stat().st_size > 0


@pytest.mark.parametrize("tab_file", FIXTURE_FILES, ids=lambda p: p.stem)
def test_no_tab_block_split_across_page(tab_file, tmp_path):
    """Regression test for #172: a [tab]...[/tab] block - after
    _reflow_tab_block()'s reflow into width-fitting systems, which is what
    actually renders - must never be split across a PDF page boundary.
    weasyprint's default pagination breaks between any two line boxes -
    including inside a tab-block's own lines - unless break-inside: avoid
    holds. Compares against the *reflowed* text, not the raw source block,
    since reflow legitimately repeats each string's label once per system
    and so no longer matches the source verbatim."""
    data = json.loads(tab_file.read_text())
    blocks = re.findall(r"\[tab\](.*?)\[/tab\]", data["tab"]["raw_tabs"], re.DOTALL)
    out_pdf = _render(tab_file, tmp_path)
    pages = [_compact(p) for p in _pdftotext_pages(out_pdf)]
    for i, block in enumerate(blocks):
        sig = _compact(sync._reflow_tab_block(block))
        if len(sig) < 5:
            continue
        assert any(sig in page for page in pages), (
            f"{tab_file.name} block {i} was split across a page boundary"
        )


@pytest.mark.parametrize("tab_file", FIXTURE_FILES, ids=lambda p: p.stem)
def test_no_mid_bar_line_wrap(tab_file, tmp_path):
    """Regression test for #174: an overlong tab line must wrap
    immediately after a "|" bar/measure separator, not mid-measure. A
    wrapped continuation line that does NOT start a fresh string (e.g.
    "e|", "B|"), a section marker, or the legend separator is only valid
    if the line it continues ended in "|" - otherwise the wrap landed
    inside a measure instead of at its boundary."""
    out_pdf = _render(tab_file, tmp_path)
    lines = "\n".join(_pdftotext_pages(out_pdf)).split("\n")
    for cur, nxt in zip(lines, lines[1:]):
        cur, nxt = cur.rstrip(), nxt.rstrip()
        if not cur or "|" not in cur or cur.endswith("|"):
            continue
        nxt_stripped = nxt.strip()
        if not nxt_stripped:
            continue
        if STRING_LINE.match(nxt_stripped) or nxt_stripped.startswith(("[", "*")):
            continue
        assert not re.match(r"^[\-0-9]", nxt_stripped), (
            f"{tab_file.name}: suspected mid-bar wrap: {cur!r} -> {nxt!r}"
        )


def test_reflow_keeps_measures_grouped_across_strings():
    """Regression test for the operator's "arpeggio line wraps and one
    string's leftover measure lands between two OTHER strings' lines"
    report: independent per-line wrapping breaks tab notation's
    vertical string-to-string alignment. Wrapping must happen between
    whole measures, with every string's matching measure landing in the
    same system, labels repeated on each one."""
    measure = "-1-2-3-4-5-6-7-8-9-0-1-2-3-4-|"  # 30 chars, forces >1 per system
    block = "\n".join(f"{label}|{measure * 4}" for label in "eBGDAE")
    reflowed = sync._reflow_tab_block(block, max_width=72)
    systems = reflowed.split("\n\n")
    assert len(systems) > 1
    for system in systems:
        labels_in_system = [line[0] for line in system.split("\n")]
        assert labels_in_system == list("eBGDAE")


def test_reflow_passes_through_leading_prose_header():
    """UG includes chord-name/comment header lines INSIDE [tab]...[/tab],
    before the actual string lines - those must survive untouched, with
    reflow still applied to the string lines that follow."""
    block = "    A    Am7\ne|-1-|-2-|\nB|-1-|-2-|"
    reflowed = sync._reflow_tab_block(block, max_width=72)
    lines = reflowed.split("\n")
    assert lines[0] == "    A    Am7"
    assert lines[1].startswith("e|")
    assert lines[2].startswith("B|")


def test_reflow_real_arpeggio_block_stays_aligned():
    """The exact reported case: Somewhere Over The Rainbow's closing
    arpeggio ("A Am7 B/A A#/A Aadd9...") is wide enough to need wrapping,
    and its [tab] block leads with a chord-name header line."""
    data = json.loads(
        (FIXTURES_DIR / "somewhereovertherainbow.ultimatetab.json").read_text()
    )
    blocks = re.findall(r"\[tab\](.*?)\[/tab\]", data["tab"]["raw_tabs"], re.DOTALL)
    block = next(b for b in blocks if "Aadd9" in b)
    reflowed = sync.render_body_html(f"[tab]{block}[/tab]")
    # Isolate the systems (skip the leading chord-name header line).
    systems = "\n".join(reflowed.split("\n")[2:]).split("\n\n")
    assert len(systems) > 1, "expected this block to actually need wrapping"
    for system in systems:
        labels_in_system = re.findall(r"^([A-Za-z0-9#]{1,3})\|", system, re.MULTILINE)
        assert labels_in_system == list("eBGDAE")


def test_legend_entities_are_not_double_escaped(tmp_path):
    """Regression test for #173: raw_tabs with pre-HTML-escaped entities
    (UG's own "Tablature Legend" footer, e.g. literal "&lt;&gt;") must
    render as the real characters, not literal escaped-entity text."""
    bluemoon = FIXTURES_DIR / "bluemoon.ultimatetab.json"
    out_pdf = _render(bluemoon, tmp_path)
    text = "\n".join(_pdftotext_pages(out_pdf))
    assert "&lt;" not in text
    assert "&amp;" not in text
    assert "<>" in text


def test_chord_tag_becomes_bold():
    assert sync.render_body_html("[ch]F#m9[/ch]") == "<b>F#m9</b>"


def test_tab_block_tag_becomes_span_with_wbr_after_bars():
    body = sync.render_body_html("[tab]e|---|\nB|---|[/tab]")
    assert body == '<span class="tab-block">e|<wbr>---|<wbr>\nB|<wbr>---|<wbr></span>'


def test_artificial_harmonic_brackets_survive_untouched():
    """[12] is a literal artificial-harmonic marker in real tab notation,
    not UG markup - must not be caught by the [tab]/[ch] regexes."""
    body = sync.render_body_html("e|--[12]--|")
    assert "[12]" in body


def test_section_label_brackets_survive_untouched():
    body = sync.render_body_html("[Verse 1]\ne|---|")
    assert "[Verse 1]" in body


def test_malformed_tab_raises(tmp_path):
    bad_file = tmp_path / "bad.ultimatetab.json"
    bad_file.write_text(json.dumps({"tab": {}}))
    with pytest.raises(sync.MalformedTabError):
        sync.convert_to_pdf(bad_file, tmp_path / "out.pdf")
