"""Tests for rendering SongHub's saved transposition: SongHub writes the
transposed sheet to tab.raw_tabs_transposed, and the PDF must use it."""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import sync  # noqa: E402


def _pdf_words(tab: dict, tmp_path: Path) -> list:
    tab_file = tmp_path / "t.ultimatetab.json"
    tab_file.write_text(json.dumps({"tab": tab}))
    out_pdf = tmp_path / "t.pdf"
    sync.convert_to_pdf(tab_file, out_pdf)
    return subprocess.run(
        ["pdftotext", str(out_pdf), "-"], capture_output=True, text=True, check=True
    ).stdout.split()


def test_pdf_uses_transposed_raw_tabs(tmp_path):
    # No transpose field: the sidecar must not compute anything itself.
    tab = {
        "raw_tabs": "[ch]Db[/ch] [ch]Bbm[/ch]",
        "raw_tabs_transposed": "[ch]D[/ch] [ch]Bm[/ch]",
    }
    assert _pdf_words(tab, tmp_path) == ["D", "Bm"]


def test_pdf_falls_back_to_raw_tabs(tmp_path):
    assert _pdf_words({"raw_tabs": "[ch]Db[/ch] [ch]Bbm[/ch]"}, tmp_path) == ["Db", "Bbm"]
