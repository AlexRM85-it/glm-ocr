"""Test per app/markitdown_loader.py (Stage B)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import markitdown_loader as ml  # noqa: E402


# -----------------------------------------------------------------------------
# is_markitdown_ext
# -----------------------------------------------------------------------------

@pytest.mark.parametrize("name", [
    "doc.docx", "slide.pptx", "sheet.xlsx", "page.html", "page.htm",
    "data.csv", "data.json", "data.xml", "book.epub",
])
def test_is_markitdown_ext_supported(name):
    assert ml.is_markitdown_ext(name) is True


def test_is_markitdown_ext_case_insensitive():
    assert ml.is_markitdown_ext("REPORT.DOCX") is True


@pytest.mark.parametrize("name", ["scan.pdf", "photo.png", "image.jpeg", "weird.xyz", "noext"])
def test_is_markitdown_ext_unsupported(name):
    assert ml.is_markitdown_ext(name) is False


# -----------------------------------------------------------------------------
# convert_to_markdown
# -----------------------------------------------------------------------------

def test_convert_csv_returns_content():
    csv_bytes = b"nome,prezzo\nmattone,0.50\nsabbia,12.00\n"
    md = ml.convert_to_markdown(csv_bytes, "listino.csv")
    assert isinstance(md, str)
    assert "mattone" in md
    assert "sabbia" in md


def test_convert_json_returns_content():
    json_bytes = b'{"citta": "Roma", "cap": "00100"}'
    md = ml.convert_to_markdown(json_bytes, "dati.json")
    assert isinstance(md, str)
    assert "Roma" in md


def test_convert_unknown_suffix_raises():
    with pytest.raises(Exception):
        ml.convert_to_markdown(b"\x00\x01garbage", "file.xyz")
