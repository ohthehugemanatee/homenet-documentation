"""Tests for applying SongHub's tab.transpose to raw_tabs chords. Spelling
must match SongHub's src/lib/core/transpose.ts."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import sync  # noqa: E402

RAW = "[ch]Db[/ch] [ch]Bbm[/ch]\nI love [ch]Ebm[/ch] [ch]Ab[/ch] [ch]Ab/C[/ch] [ch]N.C.[/ch]\n[tab]e|--[12]--|[/tab]"


def test_semitone_up_from_db_uses_sharp_key_spelling():
    tab = {"tonality": "unknown", "raw_tabs": RAW, "transpose": 1}
    assert sync.transposed_raw_tabs(tab) == (
        "[ch]D[/ch] [ch]Bm[/ch]\nI love [ch]Em[/ch] [ch]A[/ch] [ch]A/C#[/ch] [ch]N.C.[/ch]\n[tab]e|--[12]--|[/tab]"
    )


def test_flat_target_key_uses_flats():
    tab = {"raw_tabs": RAW, "transpose": 2}
    assert sync.transposed_raw_tabs(tab).startswith("[ch]Eb[/ch] [ch]Cm[/ch]")


@pytest.mark.parametrize("transpose", [None, 0, 12, -12])
def test_no_transpose_leaves_raw_tabs_unchanged(transpose):
    tab = {"raw_tabs": RAW}
    if transpose is not None:
        tab["transpose"] = transpose
    assert sync.transposed_raw_tabs(tab) == RAW


def test_negative_transpose_wraps():
    assert sync.transposed_raw_tabs({"raw_tabs": RAW, "transpose": -11}) == sync.transposed_raw_tabs(
        {"raw_tabs": RAW, "transpose": 1}
    )


@pytest.mark.parametrize(
    "key,chord,semitones,expected",
    [
        ("Am", "Am7", 1, "Bbm7"),
        ("Em", "Em", -1, "Ebm"),
        ("Cmaj7", "Cmaj7", 1, "Dbmaj7"),
        ("G", "G", 1, "Ab"),
        ("Bm", "Bm", 1, "Cm"),
        ("F#m", "F#m", 1, "Gm"),
        ("Bm", "Bm", 2, "C#m"),
    ],
)
def test_spelling_matches_songhub(key, chord, semitones, expected):
    tab = {"tonality": key, "raw_tabs": f"[ch]{chord}[/ch]", "transpose": semitones}
    assert sync.transposed_raw_tabs(tab) == f"[ch]{expected}[/ch]"


def test_key_comes_from_tonality_before_first_chord():
    # Bb +1 is B major (sharps); C +1 alone would be Db major (flats).
    raw = "[ch]C[/ch]"
    assert sync.transposed_raw_tabs({"tonality": "Bb", "raw_tabs": raw, "transpose": 1}) == "[ch]C#[/ch]"
    assert sync.transposed_raw_tabs({"tonality": "unknown", "raw_tabs": raw, "transpose": 1}) == "[ch]Db[/ch]"


def test_pdf_shows_transposed_chords(tmp_path):
    tab_file = tmp_path / "t.ultimatetab.json"
    tab_file.write_text(json.dumps({"tab": {"raw_tabs": "[ch]Db[/ch] [ch]Bbm[/ch]", "transpose": 1}}))
    out_pdf = tmp_path / "t.pdf"
    sync.convert_to_pdf(tab_file, out_pdf)
    text = subprocess.run(
        ["pdftotext", str(out_pdf), "-"], capture_output=True, text=True, check=True
    ).stdout
    assert text.split() == ["D", "Bm"]
