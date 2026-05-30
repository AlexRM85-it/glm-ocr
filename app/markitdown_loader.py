"""Conversione formati Office/Web/dati -> markdown via MarkItDown (Stage B v0.4.0).

Molti documenti NON sono scansioni: .docx/.pptx/.xlsx/.html/.csv/.json/.xml/.epub
hanno gia' una struttura testuale. Per questi NON serve il modello OCR vision:
li convertiamo direttamente in markdown con la libreria MarkItDown di Microsoft.

Ogni file di questo tipo genera UNA "pagina sintetica" (nessuna immagine sorgente):
nel page_map dell'app la sentinella e' local_idx == -2.

Il modulo e' volutamente indipendente da Streamlit (testabile da solo). L'import
di `markitdown` e' lazy (dentro convert_to_markdown) cosi' l'app si avvia anche se
la dipendenza manca: l'errore emerge solo al momento della conversione.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

# Estensioni gestite da MarkItDown (Office via extra, il resto dal core).
SUPPORTED_MARKITDOWN_EXTS = {
    ".docx", ".pptx", ".xlsx", ".html", ".htm", ".csv", ".json", ".xml", ".epub",
}


def is_markitdown_ext(name: str) -> bool:
    """True se l'estensione del filename e' gestita da MarkItDown (case-insensitive)."""
    return Path(name).suffix.lower() in SUPPORTED_MARKITDOWN_EXTS


def convert_to_markdown(file_bytes: bytes, filename: str) -> str:
    """Converte i bytes di un documento in markdown.

    MarkItDown dispatcha sul suffisso del path, quindi scriviamo i bytes in un
    tempfile con l'estensione corretta. Lazy-import di markitdown: se la dep manca
    o la conversione fallisce, solleva un'eccezione (gestita dal chiamante).
    """
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_MARKITDOWN_EXTS:
        raise ValueError(f"Estensione non supportata da MarkItDown: {filename!r}")

    from markitdown import MarkItDown  # lazy: app deve avviarsi anche senza la dep

    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(fd, "wb") as fh:
            fh.write(file_bytes)
        result = MarkItDown().convert(tmp_path)
        return (result.text_content or "").strip()
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
