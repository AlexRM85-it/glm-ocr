"""Estrazione testo dal layer testuale dei PDF (fast-path v0.3.0).

Molti PDF "prezzario"/born-digital hanno gia' il testo selezionabile: in quei
casi NON serve l'OCR del modello vision (che e' lento e, sul modello 1.1B,
sbaglia su layout multi-colonna). Qui decidiamo per-pagina se la pagina ha un
text layer usabile ed estraiamo il testo direttamente con PyMuPDF.

Il modulo e' volutamente indipendente da Streamlit per essere testabile da solo.

Metodi per-pagina ("page method"):
  - "text" : ha un text layer usabile (o e' una pagina vuota) -> estrazione diretta
  - "ocr"  : scansione / immagine a piena pagina -> serve il modello vision
"""
from __future__ import annotations

import fitz  # PyMuPDF


# Soglia minima di caratteri (strip) perche' una pagina sia considerata "con testo".
TEXT_LAYER_MIN_CHARS = 100

# Se una singola immagine copre almeno questa frazione dell'area pagina, la
# pagina e' con ogni probabilita' una scansione -> va all'OCR anche se per caso
# avesse un piccolo text layer.
FULL_PAGE_IMAGE_COVERAGE = 0.80


def _page_dominated_by_image(page) -> bool:
    """True se la pagina e' coperta da una grande immagine raster (scansione)."""
    try:
        page_area = abs(page.rect.width * page.rect.height)
        if page_area <= 0:
            return False
        for info in page.get_image_info():
            bbox = info.get("bbox")
            if not bbox:
                continue
            w = abs(bbox[2] - bbox[0])
            h = abs(bbox[3] - bbox[1])
            if (w * h) >= FULL_PAGE_IMAGE_COVERAGE * page_area:
                return True
    except Exception:  # noqa: BLE001 -- euristica best-effort, mai fatale
        return False
    return False


def classify_pdf_pages(pdf_bytes: bytes, min_chars: int = TEXT_LAYER_MIN_CHARS) -> list[str]:
    """Decide il metodo di estrazione per OGNI pagina del PDF.

    Apre il documento UNA sola volta. Ritorna una lista di "text" | "ocr",
    lunga quanto il numero di pagine.

    - "text": text layer usabile e non scansione a piena pagina; include anche
      le pagine completamente vuote (nessun testo, nessuna immagine) cosi' da
      non sprecare una chiamata OCR su una pagina bianca.
    - "ocr": scansione o immagine -> serve il modello vision.
    """
    methods: list[str] = []
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for page in doc:
            text_len = len(page.get_text().strip())
            has_imgs = bool(page.get_images())
            if text_len >= min_chars and not _page_dominated_by_image(page):
                methods.append("text")
            elif text_len == 0 and not has_imgs:
                methods.append("text")  # pagina vuota: niente da OCR
            else:
                methods.append("ocr")
    return methods


def extract_pdf_text_pages(pdf_bytes: bytes, page_indices) -> dict:
    """Estrae il testo (reading-order) per un sottoinsieme di pagine.

    Apre il documento UNA sola volta. Ritorna {page_index: testo}. Le pagine
    fuori range vengono ignorate. Usa sort=True per ordine di lettura corretto
    sui layout a piu' colonne.
    """
    wanted = sorted(set(page_indices))
    out: dict[int, str] = {}
    if not wanted:
        return out
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        n = len(doc)
        for idx in wanted:
            if 0 <= idx < n:
                out[idx] = doc[idx].get_text(sort=True).strip()
    return out


def extract_pdf_page_text(pdf_bytes: bytes, page_index: int) -> str:
    """Estrae il testo di UNA pagina in reading-order (multi-colonna safe)."""
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        if page_index < 0 or page_index >= len(doc):
            raise IndexError(f"Pagina {page_index} fuori range (0-{len(doc) - 1})")
        return doc[page_index].get_text(sort=True).strip()
