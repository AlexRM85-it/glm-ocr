"""E2E wiring di Stage B (MarkItDown) senza far girare Streamlit.

Importa app.py e sostituisce `app.st` con un fake la cui session_state e' un dict
ad accesso-attributo. Esercita: _build_page_map (mappa -2), _apply_markitdown
(conversione + page_methods), _get_page (None per -2), _build_md_content
(skip-warning), _is_markitdown_page.
"""
import io
import sys
import types
from pathlib import Path

import fitz  # PyMuPDF
import pytest
from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import app  # noqa: E402


class _State(dict):
    """dict con accesso sia ad attributo sia a chiave (mima st.session_state)."""
    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError as e:
            raise AttributeError(k) from e

    def __setattr__(self, k, v):
        self[k] = v


@pytest.fixture
def fake_st(monkeypatch):
    st = types.SimpleNamespace(session_state=_State())
    monkeypatch.setattr(app, "st", st)
    return st


def _xlsx_bytes() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["voce", "prezzo"])
    ws.append(["calcestruzzo", 95.5])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _pdf_bytes() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Pagina PDF di prova con testo selezionabile.")
    data = doc.tobytes()
    doc.close()
    return data


def test_build_page_map_mixed():
    specs = [
        ("listino.xlsx", _xlsx_bytes()),
        ("note.csv", b"a,b\n1,2\n"),
        ("doc.pdf", _pdf_bytes()),
    ]
    page_map, total = app._build_page_map(specs)
    assert total == 3
    assert page_map[0] == (0, -2)   # xlsx -> markitdown
    assert page_map[1] == (1, -2)   # csv  -> markitdown
    assert page_map[2] == (2, 0)    # pdf  -> pagina 0


def test_apply_markitdown_converts_and_skips_pdf(fake_st):
    specs = [("listino.xlsx", _xlsx_bytes()), ("doc.pdf", _pdf_bytes())]
    page_map, total = app._build_page_map(specs)
    s = fake_st.session_state
    s.page_map = page_map
    s.source_bytes = [b for _, b in specs]
    s.source_names = [n for n, _ in specs]
    s.ocr_results = [None] * total
    s.ocr_errors = [None] * total
    s.page_states = ["pending"] * total
    s.page_methods = ["ocr"] * total

    app._apply_markitdown()

    assert s.page_methods[0] == "markitdown"
    assert s.page_states[0] == "success"
    assert "calcestruzzo" in s.ocr_results[0]
    # la pagina PDF NON e' toccata da markitdown
    assert s.page_methods[1] == "ocr"
    assert s.page_states[1] == "pending"


def test_get_page_returns_none_for_markitdown(fake_st):
    s = fake_st.session_state
    s.page_map = [(0, -2)]
    s.pages = [None]
    s.source_bytes = [_xlsx_bytes()]
    s.source_names = ["x.xlsx"]
    assert app._get_page(0) is None


def test_is_markitdown_page(fake_st):
    s = fake_st.session_state
    s.page_map = [(0, -2), (1, 0), (2, -1)]
    assert app._is_markitdown_page(0) is True
    assert app._is_markitdown_page(1) is False
    assert app._is_markitdown_page(2) is False


def test_build_md_content_skip_warning(fake_st):
    s = fake_st.session_state
    s.page_map = [(0, -2)]
    s.source_names = ["broken.docx"]
    s.source_bytes = [b"x"]
    s.ocr_results = [None]
    s.ocr_errors = ["Conversione MarkItDown fallita: boom"]
    s.page_states = ["skipped"]
    md = app._build_md_content()
    assert "⚠️" in md
    assert "broken.docx" in md
    assert "boom" in md
