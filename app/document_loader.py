"""Caricamento documenti: PDF e immagini -> lista uniforme di PIL.Image."""

from __future__ import annotations

import base64
import io
from typing import Callable, Iterable

import fitz  # PyMuPDF
from PIL import Image


SUPPORTED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
SUPPORTED_PDF_EXTS = {".pdf"}

ProgressCallback = Callable[[int, int], None]  # (done, total)


def load_pdf(
    pdf_bytes: bytes,
    dpi: int = 200,
    on_progress: ProgressCallback | None = None,
    progress_offset: int = 0,
    progress_total: int | None = None,
) -> list[Image.Image]:
    """Renderizza ogni pagina del PDF come immagine PIL al DPI indicato.
    Se `on_progress` e' presente, lo chiama dopo ogni pagina renderizzata
    passando (done_assoluto, total_assoluto) -- utili quando il chiamante
    sta concatenando piu' documenti."""
    pages: list[Image.Image] = []
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        total = progress_total if progress_total is not None else len(doc)
        for i, page in enumerate(doc):
            pix = page.get_pixmap(dpi=dpi, alpha=False)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            pages.append(img)
            if on_progress:
                on_progress(progress_offset + i + 1, total)
    return pages


def load_image_bytes(file_bytes: bytes) -> Image.Image:
    """Apre un'immagine da bytes e la converte in RGB."""
    img = Image.open(io.BytesIO(file_bytes))
    if img.mode != "RGB":
        img = img.convert("RGB")
    return img


def count_total_pages(files: Iterable, file_bytes_cache: dict | None = None) -> int:
    """Conta il numero totale di pagine senza renderizzare (pre-pass leggero).
    Apre i PDF con PyMuPDF solo per leggere `page_count`. Per le immagini conta 1.
    Se `file_bytes_cache` e' un dict, salva i bytes letti per riusarli in
    `load_uploaded_files` (evita doppia lettura)."""
    total = 0
    for f in files:
        name = (getattr(f, "name", "") or "").lower()
        # Streamlit UploadedFile e' seekable; lo riavvolgiamo dopo.
        data = f.read() if hasattr(f, "read") else bytes(f)
        if hasattr(f, "seek"):
            f.seek(0)
        if file_bytes_cache is not None:
            file_bytes_cache[name] = data
        if any(name.endswith(ext) for ext in SUPPORTED_PDF_EXTS):
            with fitz.open(stream=data, filetype="pdf") as doc:
                total += len(doc)
        elif any(name.endswith(ext) for ext in SUPPORTED_IMAGE_EXTS):
            total += 1
        else:
            raise ValueError(f"Formato non supportato: {name}")
    return total


def load_uploaded_files(
    files: Iterable,
    pdf_dpi: int = 200,
    on_progress: ProgressCallback | None = None,
) -> list[Image.Image]:
    """Accetta una lista di UploadedFile di Streamlit (mista PDF + immagini)
    e restituisce la sequenza appiattita di pagine come PIL.Image.

    Se `on_progress` e' presente, chiama (done, total) durante il caricamento.
    Per ottenere il `total` corretto fa un pre-pass leggero che conta le pagine
    PDF e le immagini."""
    files_list = list(files)

    bytes_cache: dict[str, bytes] = {}
    total = count_total_pages(files_list, file_bytes_cache=bytes_cache)

    pages: list[Image.Image] = []
    done = 0

    for f in files_list:
        name = (getattr(f, "name", "") or "").lower()
        data = bytes_cache.get(name)
        if data is None:
            data = f.read() if hasattr(f, "read") else bytes(f)

        if any(name.endswith(ext) for ext in SUPPORTED_PDF_EXTS):
            new_pages = load_pdf(
                data,
                dpi=pdf_dpi,
                on_progress=on_progress,
                progress_offset=done,
                progress_total=total,
            )
            pages.extend(new_pages)
            done += len(new_pages)
        elif any(name.endswith(ext) for ext in SUPPORTED_IMAGE_EXTS):
            pages.append(load_image_bytes(data))
            done += 1
            if on_progress:
                on_progress(done, total)
        else:
            raise ValueError(f"Formato non supportato: {name}")

    return pages


def load_pdf_page(pdf_bytes: bytes, page_index: int, dpi: int = 200) -> Image.Image:
    """Renderizza UNA singola pagina di un PDF (usata dalla cache lazy per
    rigenerare solo le pagine che l'utente naviga effettivamente)."""
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        if page_index < 0 or page_index >= len(doc):
            raise IndexError(f"Pagina {page_index} fuori range (0-{len(doc)-1})")
        page = doc[page_index]
        pix = page.get_pixmap(dpi=dpi, alpha=False)
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def to_base64_png(img: Image.Image) -> str:
    """Serializza l'immagine in PNG base64 (formato richiesto da Ollama)."""
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")
