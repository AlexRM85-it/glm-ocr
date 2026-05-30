"""GLM-OCR Webapp - converte PDF/immagini scansionati in markdown via Ollama."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

import fitz  # PyMuPDF, per load_pdf_page lazy
import streamlit as st

from applog import get_logger, logs_dir
from document_loader import (
    SUPPORTED_IMAGE_EXTS,
    SUPPORTED_PDF_EXTS,
    count_total_pages,
    load_image_bytes,
    load_pdf,
    load_pdf_page,
)
import folder_picker
import parent_watchdog
from help_content import HELP_MARKDOWN
from markitdown_loader import SUPPORTED_MARKITDOWN_EXTS, is_markitdown_ext
from ocr_client import (
    DEFAULT_HOST,
    DEFAULT_MODEL,
    check_ollama_available,
    ocr_image_with_retry,
)
from ocr_job import OcrJob
from ocr_store import OcrStore, SessionState, SourceFileMeta
import updater


logger = get_logger()


# -----------------------------------------------------------------------------
# Config persistente (data/config.json) - solo preferenze utente
# -----------------------------------------------------------------------------

def _data_dir() -> Path:
    d = Path(__file__).resolve().parent.parent / "data"
    d.mkdir(exist_ok=True)
    return d


def _load_config() -> dict:
    cfg_path = _data_dir() / "config.json"
    if cfg_path.is_file():
        try:
            return json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            logger.exception("config.json corrotto, ignorato")
    return {}


def _save_config(cfg: dict) -> None:
    cfg_path = _data_dir() / "config.json"
    try:
        cfg_path.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:  # noqa: BLE001
        logger.exception("Impossibile salvare config.json")


# -----------------------------------------------------------------------------
# Session state helpers
# -----------------------------------------------------------------------------

def _init_state() -> None:
    cfg = _load_config()
    default_out = cfg.get("output_dir") or str(folder_picker.default_output_dir())

    defaults = {
        # File loading state
        "file_hash": None,
        "source_bytes": [],          # list[bytes] - bytes raw per file sorgente
        "source_names": [],          # list[str] - nomi originali
        "page_map": [],              # list[(source_idx, local_page_idx | -1)]
        "pages": [],                 # list[PIL.Image | None] - lazy nel post-restore
        "pdf_dpi": 300,
        # OCR state
        "ocr_results": [],
        "ocr_errors": [],
        "page_states": [],           # "pending"|"success"|"error"|"skipped"
        "page_methods": [],          # "ocr"|"text"|"markitdown" per pagina
        "current_page": 0,
        "last_run_completed": False,
        # OCR job
        "ocr_job": None,             # OcrJob | None
        "ocr_mode_at_start": None,   # "Sequenziale"|"Parallela" (snapshot)
        # Output / cache
        "output_dir": default_out,
        "restore_pending": False,    # banner ripristino sessione
        "restore_state": None,       # SessionState candidata al ripristino
        # Update
        "update_checked": False,
        "update_info": None,
        "update_staged": False,
        "update_error": None,
        # Uploader / ciclo di vita sessione
        "loaded_via_uploader": False,  # True se la sessione attiva viene dall'uploader (non da restore)
        "uploader_key": 0,             # bump per forzare il reset del widget file_uploader
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def _reset_pages_state(pages_count: int) -> None:
    st.session_state.ocr_results = [None] * pages_count
    st.session_state.ocr_errors = [None] * pages_count
    st.session_state.page_states = ["pending"] * pages_count
    st.session_state.page_methods = ["ocr"] * pages_count
    st.session_state.current_page = 0
    st.session_state.last_run_completed = False
    st.session_state.ocr_job = None


def _clear_session() -> None:
    """Azzera completamente lo stato in memoria della sessione corrente
    (file, pagine, risultati) e forza il reset del widget uploader.
    Usato quando l'utente toglie il file con la X o pulisce la cache."""
    job = st.session_state.get("ocr_job")
    if job is not None:
        try:
            job.cancel()
        except Exception:  # noqa: BLE001
            logger.exception("Cancel job durante clear sessione fallito")
    st.session_state.file_hash = None
    st.session_state.source_bytes = []
    st.session_state.source_names = []
    st.session_state.page_map = []
    st.session_state.pages = []
    st.session_state.ocr_results = []
    st.session_state.ocr_errors = []
    st.session_state.page_states = []
    st.session_state.page_methods = []
    st.session_state.current_page = 0
    st.session_state.last_run_completed = False
    st.session_state.ocr_job = None
    st.session_state.loaded_via_uploader = False
    # Bump della key: rende vuoto il file_uploader al prossimo render.
    st.session_state.uploader_key += 1


def _files_hash(files) -> str:
    h = hashlib.sha256()
    for f in files:
        h.update((f.name or "").encode("utf-8"))
        h.update(str(getattr(f, "size", 0)).encode("utf-8"))
    return h.hexdigest()


def _bytes_hash(items: list[tuple[str, bytes]]) -> str:
    h = hashlib.sha256()
    for name, b in items:
        h.update(name.encode("utf-8"))
        h.update(str(len(b)).encode("utf-8"))
    return h.hexdigest()


# -----------------------------------------------------------------------------
# Lazy page rendering
# -----------------------------------------------------------------------------

def _get_page(i: int):
    """Ritorna pages[i] renderizzata (cache RAM). Se None, la rigenera dal
    source bytes corrispondente (post-cache-restore)."""
    page = st.session_state.pages[i]
    if page is not None:
        return page
    src_idx, local_idx = st.session_state.page_map[i]
    if local_idx == -2:
        return None  # pagina MarkItDown: nessuna immagine da renderizzare
    data = st.session_state.source_bytes[src_idx]
    name = st.session_state.source_names[src_idx].lower()
    if local_idx == -1:
        img = load_image_bytes(data)
    else:
        img = load_pdf_page(data, local_idx, dpi=st.session_state.pdf_dpi)
    st.session_state.pages[i] = img
    return img


# -----------------------------------------------------------------------------
# OcrStore helpers
# -----------------------------------------------------------------------------

def _store() -> OcrStore:
    return OcrStore(st.session_state.output_dir)


def _persist_state() -> None:
    """Scrive lo stato corrente in cache (atomic)."""
    if not st.session_state.source_names:
        return
    try:
        store = _store()
        state = SessionState(
            file_hash=st.session_state.file_hash or "",
            source_files=[
                SourceFileMeta(name=n, size=len(b), stored_as=f"source_{i:03d}{Path(n).suffix.lower() or '.bin'}")
                for i, (n, b) in enumerate(zip(st.session_state.source_names, st.session_state.source_bytes))
            ],
            pdf_dpi=st.session_state.pdf_dpi,
            pages_count=len(st.session_state.page_states),
            page_states=list(st.session_state.page_states),
            ocr_results=list(st.session_state.ocr_results),
            ocr_errors=list(st.session_state.ocr_errors),
            current_page=st.session_state.current_page,
            page_methods=list(st.session_state.get("page_methods", [])),
        )
        store.save(state)
    except Exception:  # noqa: BLE001
        logger.exception("Salvataggio cache fallito")


# -----------------------------------------------------------------------------
# OCR result handling
# -----------------------------------------------------------------------------

def _on_result(i: int, md: str | None, err: str | None) -> None:
    """Aggiorna lo stato di una singola pagina e persiste la cache."""
    if md is not None:
        st.session_state.ocr_results[i] = md
        st.session_state.ocr_errors[i] = None
        st.session_state.page_states[i] = "success"
    else:
        st.session_state.ocr_results[i] = None
        st.session_state.ocr_errors[i] = err
        st.session_state.page_states[i] = "error"


def _retry_single_page(i: int, model: str, host: str) -> None:
    try:
        md = ocr_image_with_retry(_get_page(i), model=model, host=host)
        _on_result(i, md, None)
    except Exception as e:  # noqa: BLE001
        _on_result(i, None, str(e))
        logger.exception("Retry pagina %d fallito", i)
    _persist_state()


def _is_markitdown_page(i: int) -> bool:
    """True se la pagina i e' una pagina sintetica MarkItDown (local_idx == -2)."""
    page_map = st.session_state.get("page_map", [])
    return 0 <= i < len(page_map) and page_map[i][1] == -2


def _retry_markitdown_page(i: int) -> None:
    """Ri-tenta la conversione MarkItDown della pagina i (no OCR)."""
    import markitdown_loader
    src, _local = st.session_state.page_map[i]
    name = st.session_state.source_names[src] if src < len(st.session_state.source_names) else ""
    try:
        md = markitdown_loader.convert_to_markdown(st.session_state.source_bytes[src], name)
        st.session_state.ocr_results[i] = md
        st.session_state.ocr_errors[i] = None
        st.session_state.page_states[i] = "success"
    except Exception as e:  # noqa: BLE001
        st.session_state.ocr_results[i] = None
        st.session_state.ocr_errors[i] = f"Conversione MarkItDown fallita: {e}"
        st.session_state.page_states[i] = "error"
        logger.exception("Retry MarkItDown pagina %d fallito", i)
    _persist_state()


# -----------------------------------------------------------------------------
# OCR job launching
# -----------------------------------------------------------------------------

def _start_ocr_job(indices: list[int], mode: str, model: str, host: str, workers: int) -> None:
    if not indices:
        return
    # Reset pagine target.
    for i in indices:
        st.session_state.page_states[i] = "pending"
        st.session_state.ocr_errors[i] = None
        st.session_state.ocr_results[i] = None

    initial_workers = workers if mode == "Parallela" else 1
    pause_on_first_error = (mode == "Parallela")

    # Renderizza tutte le pagine target (no lazy in OCR: serve PIL.Image pronta).
    rendered_pages: list = []
    for i in range(len(st.session_state.page_states)):
        rendered_pages.append(_get_page(i))

    job = OcrJob(
        pages=rendered_pages,
        indices=indices,
        model=model,
        host=host,
        initial_workers=initial_workers,
        pause_on_first_error=pause_on_first_error,
    )
    st.session_state.ocr_job = job
    st.session_state.ocr_mode_at_start = mode
    st.session_state.last_run_completed = False
    logger.info("OCR job avviato: %d pagine, mode=%s, workers=%d",
                len(indices), mode, initial_workers)


# -----------------------------------------------------------------------------
# Help dialog (?)
# -----------------------------------------------------------------------------

@st.dialog("Come usare GLM-OCR", width="large")
def _show_help_dialog() -> None:
    """Modale guida. Si chiude con la X o cliccando fuori (comportamento nativo)."""
    st.markdown(HELP_MARKDOWN)


# -----------------------------------------------------------------------------
# Updater UI
# -----------------------------------------------------------------------------

def _check_update_on_startup() -> None:
    if st.session_state.update_checked:
        return
    st.session_state.update_checked = True
    try:
        info = updater.check_for_updates(force=False)
        st.session_state.update_info = info
    except Exception:  # noqa: BLE001
        logger.exception("Check update fallito")
        st.session_state.update_info = None


def _render_update_banner() -> None:
    info = st.session_state.update_info
    if not info or st.session_state.update_staged:
        return
    cur = updater.current_version()
    st.info(
        f"E' disponibile la versione **{info.version}** (attuale: {cur}). "
        f"Vai nella sidebar per installarla."
    )


def _render_sidebar_updates() -> None:
    st.sidebar.subheader("Aggiornamenti")
    st.sidebar.caption(f"Versione installata: `v{updater.current_version()}`")

    if not updater.is_configured():
        st.sidebar.caption("_(repository GitHub non configurato in updater.py)_")
        return

    if st.sidebar.button("Controlla aggiornamenti", use_container_width=True):
        try:
            info = updater.check_for_updates(force=True)
            st.session_state.update_info = info
            if info is None:
                st.sidebar.success("Sei aggiornato all'ultima versione.")
            else:
                st.sidebar.info(f"Disponibile v{info.version}")
        except Exception as e:  # noqa: BLE001
            logger.exception("Check update manuale fallito")
            st.sidebar.error(f"Errore controllo: {e}")

    info = st.session_state.update_info
    if info and not st.session_state.update_staged:
        if st.sidebar.button(
            f"Installa aggiornamento v{info.version}",
            type="primary",
            use_container_width=True,
        ):
            _download_update_with_progress(info)

    if st.session_state.update_staged:
        st.sidebar.success(
            "Aggiornamento scaricato. **Chiudi la finestra del terminale** e "
            "rilancia _Avvia GLM-OCR.bat_ per applicarlo."
        )


def _download_update_with_progress(info) -> None:
    progress = st.sidebar.progress(0.0, text=f"Scarico v{info.version}...")

    def on_progress(downloaded: int, total: int | None) -> None:
        if total:
            progress.progress(min(1.0, downloaded / total),
                              text=f"Scarico v{info.version}: {downloaded // 1024} KB / {total // 1024} KB")
        else:
            progress.progress(0.5, text=f"Scarico v{info.version}: {downloaded // 1024} KB")

    try:
        updater.download_and_stage(info, on_progress=on_progress)
        progress.empty()
        st.session_state.update_staged = True
        st.session_state.update_error = None
    except Exception as e:  # noqa: BLE001
        progress.empty()
        st.session_state.update_error = str(e)
        st.sidebar.error(f"Download fallito: {e}")
        logger.exception("Download update fallito")


# -----------------------------------------------------------------------------
# Sidebar rendering
# -----------------------------------------------------------------------------

def _render_sidebar() -> dict:
    # Titolo + bottone "?" guida.
    title_col, help_col = st.sidebar.columns([3, 1])
    title_col.title("GLM-OCR")
    if help_col.button("❓", help="Apri la guida", use_container_width=True):
        _show_help_dialog()
    st.sidebar.caption("PDF/immagini scansionati -> markdown pulito")

    # --- Cartella output ---
    with st.sidebar.expander("Cartella output", expanded=False):
        st.caption(st.session_state.output_dir)
        c1, c2 = st.columns(2)
        if c1.button("Cambia...", use_container_width=True,
                     disabled=not folder_picker.is_available()):
            chosen = folder_picker.pick_folder(initialdir=st.session_state.output_dir)
            if chosen:
                st.session_state.output_dir = chosen
                cfg = _load_config()
                cfg["output_dir"] = chosen
                _save_config(cfg)
                logger.info("Cartella output cambiata: %s", chosen)
                st.rerun()
        if c2.button("Apri", use_container_width=True):
            try:
                os.startfile(st.session_state.output_dir)  # type: ignore[attr-defined]
            except Exception as e:  # noqa: BLE001
                st.error(f"Impossibile aprire: {e}")
        if not folder_picker.is_available():
            st.caption("_(tkinter non disponibile: incolla path qui sotto)_")
            new_path = st.text_input("Path", value=st.session_state.output_dir)
            if new_path and new_path != st.session_state.output_dir:
                if Path(new_path).is_dir():
                    st.session_state.output_dir = new_path
                    cfg = _load_config()
                    cfg["output_dir"] = new_path
                    _save_config(cfg)
                    st.rerun()
                else:
                    st.error("Cartella inesistente")

    # --- Impostazioni Ollama ---
    with st.sidebar.expander("Impostazioni Ollama", expanded=False):
        host = st.text_input("Host Ollama", value=DEFAULT_HOST)
        model = st.text_input("Modello", value=DEFAULT_MODEL)
        dpi = st.slider("DPI rendering PDF", 100, 400, st.session_state.pdf_dpi, step=50)
        st.session_state.pdf_dpi = dpi

    # Status Ollama
    ok, msg = check_ollama_available(host=host, model=model)
    (st.sidebar.success if ok else st.sidebar.error)(msg)

    # --- Documenti ---
    st.sidebar.subheader("Documenti")
    files = st.sidebar.file_uploader(
        "Carica PDF, immagini o documenti",
        type=["pdf", "png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff",
              "docx", "pptx", "xlsx", "html", "htm", "csv", "json", "xml", "epub"],
        accept_multiple_files=True,
        key=f"uploader_{st.session_state.uploader_key}",
    )

    # --- Modalita OCR ---
    st.sidebar.subheader("Modalita' OCR")
    mode = st.sidebar.radio(
        "Esecuzione",
        options=["Sequenziale", "Parallela"],
        index=0,
        help="Sequenziale: piu' affidabile. Parallela: piu' veloce ma stressa Ollama.",
    )
    workers = st.sidebar.slider(
        "Worker paralleli", 1, 8, 3,
        help="Numero di pagine elaborate in parallelo. Modificabile anche durante l'OCR.",
    )

    job_running = st.session_state.ocr_job is not None and not st.session_state.ocr_job.is_done()
    run_clicked = st.sidebar.button(
        "Esegui OCR",
        type="primary",
        use_container_width=True,
        disabled=not ok or not files or job_running,
    )
    cancel_clicked = False
    if job_running:
        cancel_clicked = st.sidebar.button(
            "Annulla OCR", use_container_width=True, type="secondary"
        )

    # Live worker resize: se c'e' un job e l'utente sposta lo slider, propaga.
    if job_running:
        job = st.session_state.ocr_job
        status = job.status()
        # Solo se il job non e' in pausa-errore (in pausa lo slider non ha senso).
        if not status.paused_on_error and status.max_workers != workers:
            job.set_max_workers(workers)

    # --- Diagnostica ---
    with st.sidebar.expander("Diagnostica", expanded=False):
        if st.button("Apri cartella log", use_container_width=True):
            try:
                os.startfile(str(logs_dir()))  # type: ignore[attr-defined]
            except Exception as e:  # noqa: BLE001
                st.error(f"Impossibile aprire: {e}")
        if st.button("Pulisci cache sessione", use_container_width=True,
                     help="Rimuove la cache OCR su disco e svuota la sessione corrente."):
            try:
                _store().clear()
                _clear_session()
                st.success("Cache rimossa.")
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error(f"Errore: {e}")

    st.sidebar.divider()
    _render_sidebar_updates()

    return {
        "host": host,
        "model": model,
        "dpi": dpi,
        "files": files,
        "mode": mode,
        "workers": workers,
        "run_clicked": run_clicked,
        "cancel_clicked": cancel_clicked,
        "ollama_ok": ok,
    }


# -----------------------------------------------------------------------------
# Loading files (con progress)
# -----------------------------------------------------------------------------

def _build_page_map(file_specs: list[tuple[str, bytes]]) -> tuple[list[tuple[int, int]], int]:
    """Pre-pass: per ogni file conta le pagine e costruisce la mappa
    flat_idx -> (source_idx, local_idx | -1)."""
    page_map: list[tuple[int, int]] = []
    for src_idx, (name, data) in enumerate(file_specs):
        lname = name.lower()
        if any(lname.endswith(ext) for ext in SUPPORTED_PDF_EXTS):
            with fitz.open(stream=data, filetype="pdf") as doc:
                for local in range(len(doc)):
                    page_map.append((src_idx, local))
        elif any(lname.endswith(ext) for ext in SUPPORTED_IMAGE_EXTS):
            page_map.append((src_idx, -1))
        elif is_markitdown_ext(lname):
            page_map.append((src_idx, -2))  # pagina sintetica MarkItDown, no immagine
        else:
            raise ValueError(f"Formato non supportato: {name}")
    return page_map, len(page_map)


def _render_pages_with_progress(file_specs: list[tuple[str, bytes]], dpi: int, total: int) -> list:
    """Renderizza tutte le pagine con st.progress."""
    progress = st.progress(0.0, text=f"Caricamento 0/{total}...")
    pages = []
    done = 0
    for name, data in file_specs:
        lname = name.lower()
        if any(lname.endswith(ext) for ext in SUPPORTED_PDF_EXTS):
            new_pages = load_pdf(
                data, dpi=dpi,
                on_progress=lambda d, t: progress.progress(
                    min(1.0, d / t),
                    text=f"{int(d/t*100)}% — caricamento {d}/{t} pagine"
                ),
                progress_offset=done,
                progress_total=total,
            )
            pages.extend(new_pages)
            done += len(new_pages)
        elif is_markitdown_ext(lname):
            pages.append(None)  # pagina sintetica MarkItDown: nessuna immagine
            done += 1
            progress.progress(min(1.0, done / total),
                              text=f"{int(done/total*100)}% — caricamento {done}/{total} pagine")
        else:
            pages.append(load_image_bytes(data))
            done += 1
            progress.progress(min(1.0, done / total),
                              text=f"{int(done/total*100)}% — caricamento {done}/{total} pagine")
    progress.empty()
    return pages


def _apply_text_fastpath() -> None:
    """Per le pagine PDF con text layer estrae il testo direttamente (no OCR).
    Imposta page_methods e pre-popola ocr_results/page_states per quelle pagine.
    Le pagine scansione/immagine restano method="ocr" e passano dal modello."""
    import text_extract
    page_map = st.session_state.page_map
    source_bytes = st.session_state.source_bytes
    source_names = st.session_state.source_names
    methods = ["ocr"] * len(page_map)
    by_source: dict = {}
    for flat, (src, local) in enumerate(page_map):
        if local < 0:
            continue  # immagine singola -> OCR
        name = (source_names[src] if src < len(source_names) else "").lower()
        if not name.endswith(".pdf"):
            continue
        by_source.setdefault(src, []).append((flat, local))
    for src, items in by_source.items():
        try:
            data = source_bytes[src]
            cls = text_extract.classify_pdf_pages(data)
            text_locals = [local for (flat, local) in items
                           if local < len(cls) and cls[local] == "text"]
            texts = text_extract.extract_pdf_text_pages(data, text_locals)
        except Exception:  # noqa: BLE001
            logger.exception("Text fast-path fallito su source %d", src)
            continue
        for flat, local in items:
            if local < len(cls) and cls[local] == "text":
                methods[flat] = "text"
                st.session_state.ocr_results[flat] = texts.get(local, "")
                st.session_state.ocr_errors[flat] = None
                st.session_state.page_states[flat] = "success"
    st.session_state.page_methods = methods


def _apply_markitdown() -> None:
    """Per le pagine sintetiche MarkItDown (local_idx == -2) converte il documento
    in markdown (no OCR). Imposta page_methods="markitdown" e pre-popola
    ocr_results/page_states. Su errore: page_state="error" col messaggio.

    Va chiamato DOPO _apply_text_fastpath (che inizializza page_methods)."""
    import markitdown_loader
    page_map = st.session_state.page_map
    source_bytes = st.session_state.source_bytes
    source_names = st.session_state.source_names
    methods = list(st.session_state.get("page_methods", []) or ["ocr"] * len(page_map))
    for flat, (src, local) in enumerate(page_map):
        if local != -2:
            continue
        methods[flat] = "markitdown"
        name = source_names[src] if src < len(source_names) else ""
        try:
            md = markitdown_loader.convert_to_markdown(source_bytes[src], name)
            st.session_state.ocr_results[flat] = md
            st.session_state.ocr_errors[flat] = None
            st.session_state.page_states[flat] = "success"
        except Exception as e:  # noqa: BLE001
            logger.exception("Conversione MarkItDown fallita su %s", name)
            st.session_state.ocr_results[flat] = None
            st.session_state.ocr_errors[flat] = f"Conversione MarkItDown fallita: {e}"
            st.session_state.page_states[flat] = "error"
    st.session_state.page_methods = methods


def _ensure_pages_loaded(files, dpi: int) -> None:
    """Se il set di file e' cambiato, carica nuove pagine e resetta lo stato."""
    if not files:
        return
    new_hash = _files_hash(files)
    if new_hash == st.session_state.file_hash and st.session_state.page_states:
        return

    # Leggi i bytes una volta sola.
    file_specs: list[tuple[str, bytes]] = []
    for f in files:
        f.seek(0)
        file_specs.append((f.name, f.read()))
        f.seek(0)

    try:
        page_map, total = _build_page_map(file_specs)
        pages = _render_pages_with_progress(file_specs, dpi, total)
    except Exception as e:  # noqa: BLE001
        logger.exception("Caricamento file fallito")
        st.error(f"Errore nel caricamento: {e}")
        return

    # Reset cache precedente (file diverso).
    try:
        _store().clear()
    except Exception:  # noqa: BLE001
        logger.exception("Impossibile pulire cache precedente")

    # Scrivi i sorgenti su disco per consentire il restore cross-session.
    try:
        _store().save_sources(files)
    except Exception:  # noqa: BLE001
        logger.exception("Salvataggio sorgenti su cache fallito")

    st.session_state.file_hash = new_hash
    st.session_state.source_bytes = [b for _, b in file_specs]
    st.session_state.source_names = [n for n, _ in file_specs]
    st.session_state.page_map = page_map
    st.session_state.pages = pages
    _reset_pages_state(len(pages))
    _apply_text_fastpath()
    _apply_markitdown()
    st.session_state.loaded_via_uploader = True
    _persist_state()


# -----------------------------------------------------------------------------
# Restore session from cache
# -----------------------------------------------------------------------------

def _check_restore_candidate() -> None:
    """Se non c'e' una sessione attiva e la cache esiste, marca come ripristinabile."""
    if st.session_state.file_hash:
        return  # gia' attivo qualcosa
    if st.session_state.restore_pending:
        return  # gia' rilevato
    try:
        store = _store()
        if store.exists():
            state = store.load()
            if state and state.source_files:
                st.session_state.restore_pending = True
                st.session_state.restore_state = state
    except Exception:  # noqa: BLE001
        logger.exception("Check cache fallito")


def _render_restore_banner() -> None:
    if not st.session_state.restore_pending or not st.session_state.restore_state:
        return
    state: SessionState = st.session_state.restore_state
    store = _store()

    st.info(f"💾 **Sessione precedente trovata:** {store.describe(state)}")
    c1, c2 = st.columns(2)
    if c1.button("Ripristina", type="primary", use_container_width=True):
        if _do_restore(state):
            st.rerun()
    if c2.button("Scarta", use_container_width=True):
        try:
            store.clear()
        except Exception:  # noqa: BLE001
            logger.exception("Errore pulizia cache")
        st.session_state.restore_pending = False
        st.session_state.restore_state = None
        st.rerun()


def _do_restore(state: SessionState) -> bool:
    """Carica state + source bytes nel session_state. Le pagine restano None
    (lazy: renderizzate alla prima navigazione). Ritorna True se il restore
    e' riuscito, False altrimenti (in tal caso il chiamante non deve fare
    st.rerun() per non scartare l'st.error appena renderizzato)."""
    store = _store()
    source_specs = store.load_source_bytes(state)  # [(name, bytes), ...]
    if not source_specs:
        logger.warning("Restore: nessun source bytes recuperabile")
        st.error(
            "Impossibile ripristinare: file sorgente mancanti dalla cache. "
            "Usa 'Scarta' per ripulire e ricaricare il documento."
        )
        return False

    try:
        page_map, total = _build_page_map(source_specs)
    except Exception as e:  # noqa: BLE001
        logger.exception("Restore: errore page_map")
        st.error(f"Errore ripristino: {e}")
        return False

    if total != state.pages_count:
        logger.warning("Restore: pages_count mismatch (state=%d, recomputed=%d)",
                       state.pages_count, total)

    st.session_state.file_hash = state.file_hash
    st.session_state.source_bytes = [b for _, b in source_specs]
    st.session_state.source_names = [n for n, _ in source_specs]
    st.session_state.page_map = page_map
    st.session_state.pages = [None] * total
    st.session_state.pdf_dpi = state.pdf_dpi
    st.session_state.ocr_results = list(state.ocr_results) + [None] * max(0, total - len(state.ocr_results))
    st.session_state.ocr_errors = list(state.ocr_errors) + [None] * max(0, total - len(state.ocr_errors))
    st.session_state.page_states = list(state.page_states) + ["pending"] * max(0, total - len(state.page_states))
    _rm = list(getattr(state, "page_methods", []) or [])
    st.session_state.page_methods = _rm + ["ocr"] * max(0, total - len(_rm))
    st.session_state.current_page = min(state.current_page, total - 1) if total else 0
    st.session_state.last_run_completed = True
    st.session_state.restore_pending = False
    st.session_state.restore_state = None
    st.session_state.loaded_via_uploader = False  # restore da cache, non dall'uploader
    logger.info("Sessione ripristinata: %d pagine", total)
    return True


# -----------------------------------------------------------------------------
# OCR progress fragment (polling)
# -----------------------------------------------------------------------------

def _render_ocr_progress_fragment() -> None:
    """Fragment auto-refresh ogni 500ms quando un job e' in corso."""
    job = st.session_state.ocr_job
    if job is None:
        return

    @st.fragment(run_every="500ms")
    def _frag():
        j = st.session_state.ocr_job
        if j is None:
            return
        status = j.status()
        # Drena risultati nuovi.
        for idx, md, err in j.drain_new_results():
            _on_result(idx, md, err)
        _persist_state()

        pct = status.completed / status.total if status.total else 0.0
        # Blocco prominente: progress bar centrata con %.
        c1, c2, c3 = st.columns([1, 3, 1])
        with c2:
            label = "OCR in pausa (errore)" if status.paused_on_error else "OCR in corso"
            st.markdown(
                f"<div style='text-align:center;font-weight:600;font-size:1.1em;margin-bottom:0.3em'>{label}</div>",
                unsafe_allow_html=True,
            )
            st.progress(
                pct,
                text=f"{int(pct*100)}% — {status.completed}/{status.total} pagine "
                     f"(worker attivi: {status.active_workers}/{status.max_workers})",
            )

        # Quando il job e' finito, esci dal fragment e force rerun globale.
        if status.is_done or status.is_cancelled:
            st.session_state.last_run_completed = True
            # Non azzeriamo subito ocr_job: lo lasciamo per il prompt parallel error.
            if not status.paused_on_error:
                st.session_state.ocr_job = None
            st.rerun()

    _frag()


# -----------------------------------------------------------------------------
# Parallel-error prompt
# -----------------------------------------------------------------------------

def _render_parallel_prompt(cfg: dict) -> None:
    job = st.session_state.ocr_job
    if job is None or not job.is_paused_on_error():
        return
    status = job.status()
    pending = job.pending_indices()
    failed = status.failed_index
    pending_all = sorted(set(pending) | ({failed} if failed is not None else set()))

    # Marca la failed come error in stato (visibile anche se l'utente annulla).
    if failed is not None and st.session_state.page_states[failed] != "error":
        _on_result(failed, None, status.error_message or "Errore in parallelo")
        _persist_state()

    st.warning(
        f"OCR parallelo interrotto sulla pagina {failed + 1 if failed is not None else '?'}: "
        f"{status.error_message}\n\n"
        f"Pagine non processate: {[i + 1 for i in pending_all]}"
    )
    c1, c2 = st.columns(2)
    if c1.button("Annulla", use_container_width=True):
        job.cancel()
        st.session_state.ocr_job = None
        st.session_state.last_run_completed = True
        st.rerun()
    if c2.button("Continua in sequenziale", type="primary", use_container_width=True):
        # Avvia un NUOVO job sequenziale sulle pagine residue (incluso il failed).
        job.cancel()
        st.session_state.ocr_job = None
        _start_ocr_job(pending_all, "Sequenziale", cfg["model"], cfg["host"], 1)
        st.rerun()


# -----------------------------------------------------------------------------
# Skipped summary
# -----------------------------------------------------------------------------

def _render_skipped_summary(cfg: dict) -> None:
    states = st.session_state.page_states
    skipped = [i for i, s in enumerate(states) if s == "skipped"]
    if not (st.session_state.last_run_completed and skipped):
        return
    if st.session_state.ocr_job is not None:
        return
    st.warning(f"{len(skipped)} pagine saltate: {[i + 1 for i in skipped]}")
    if st.button("Riprova OCR sulle pagine skippate", type="primary"):
        _start_ocr_job(skipped, "Sequenziale", cfg["model"], cfg["host"], 1)
        st.rerun()


# -----------------------------------------------------------------------------
# Comparison view
# -----------------------------------------------------------------------------

def _render_comparison(cfg: dict) -> None:
    if not st.session_state.page_states:
        st.info("Carica un PDF o delle immagini dalla sidebar per iniziare.")
        return

    total = len(st.session_state.page_states)
    cur = st.session_state.current_page

    # Navigazione.
    nav1, nav2, nav3 = st.columns([1, 2, 1])
    with nav1:
        if st.button("< Prev", disabled=cur == 0, use_container_width=True):
            st.session_state.current_page = max(0, cur - 1)
            _persist_state()
            st.rerun()
    with nav2:
        st.markdown(
            f"<div style='text-align:center;font-weight:600'>Pagina {cur + 1} / {total}</div>",
            unsafe_allow_html=True,
        )
    with nav3:
        if st.button("Next >", disabled=cur >= total - 1, use_container_width=True):
            st.session_state.current_page = min(total - 1, cur + 1)
            _persist_state()
            st.rerun()

    left, right = st.columns(2)

    with left:
        st.subheader("Originale")
        if _is_markitdown_page(cur):
            src = st.session_state.page_map[cur][0]
            name = st.session_state.source_names[src] if src < len(st.session_state.source_names) else "?"
            size = len(st.session_state.source_bytes[src]) if src < len(st.session_state.source_bytes) else 0
            ext = (Path(name).suffix.lstrip(".").upper() or "?")
            st.info(
                f"**{name}**\n\n"
                f"Tipo: {ext} · Dimensione: {size / 1024:.1f} KB\n\n"
                f"_Documento convertito con MarkItDown (nessuna anteprima immagine)._"
            )
        else:
            try:
                img = _get_page(cur)
                st.image(img, use_container_width=True)
            except Exception as e:  # noqa: BLE001
                logger.exception("Errore rendering pagina %d", cur)
                st.error(f"Impossibile renderizzare pagina: {e}")

    with right:
        st.subheader("Markdown OCR")
        state = st.session_state.page_states[cur]
        if state == "success":
            md = st.session_state.ocr_results[cur] or ""
            tab_render, tab_source = st.tabs(["Renderizzato", "Sorgente"])
            with tab_render:
                st.markdown(md, unsafe_allow_html=False)
            with tab_source:
                st.code(md, language="markdown")
        elif state == "error":
            err = st.session_state.ocr_errors[cur] or "Errore sconosciuto"
            st.error(err)
            is_md = _is_markitdown_page(cur)
            b1, b2 = st.columns(2)
            if b1.button("Riprova", key=f"retry_{cur}", use_container_width=True):
                with st.spinner("Riprovo conversione..." if is_md else "Riprovo OCR..."):
                    if is_md:
                        _retry_markitdown_page(cur)
                    else:
                        _retry_single_page(cur, cfg["model"], cfg["host"])
                st.rerun()
            if b2.button("Skippa", key=f"skip_{cur}", use_container_width=True):
                st.session_state.page_states[cur] = "skipped"
                # Per le pagine MarkItDown conserviamo il messaggio d'errore: finira'
                # come warning visibile nel .md finale (richiesta utente).
                if not is_md:
                    st.session_state.ocr_errors[cur] = None
                _persist_state()
                st.rerun()
        elif state == "skipped":
            st.info("Pagina saltata.")
            is_md = _is_markitdown_page(cur)
            if st.button("Riprova ora", key=f"unskip_{cur}"):
                with st.spinner("Riprovo conversione..." if is_md else "Riprovo OCR..."):
                    if is_md:
                        _retry_markitdown_page(cur)
                    else:
                        _retry_single_page(cur, cfg["model"], cfg["host"])
                st.rerun()
        else:  # pending
            st.info("Pagina non ancora processata. Clicca 'Esegui OCR' nella sidebar.")


# -----------------------------------------------------------------------------
# Download / Save .md
# -----------------------------------------------------------------------------

def _build_md_content() -> str:
    results = st.session_state.ocr_results
    states = st.session_state.page_states
    parts: list[str] = []
    for i, (md, state) in enumerate(zip(results, states), start=1):
        parts.append(f"## Page {i}\n")
        if state == "success":
            parts.append((md or "").strip())
        elif state == "skipped":
            if _is_markitdown_page(i - 1):
                src = st.session_state.page_map[i - 1][0]
                name = (st.session_state.source_names[src]
                        if src < len(st.session_state.source_names) else "?")
                err = st.session_state.ocr_errors[i - 1] or "conversione fallita"
                parts.append(f"> ⚠️ Conversione MarkItDown fallita per «{name}»: {err}")
            else:
                parts.append(f"> Pagina {i} saltata dall'utente.")
        elif state == "error":
            err = st.session_state.ocr_errors[i - 1] or ""
            parts.append(f"> Pagina {i} non processata. Errore: {err}")
        else:
            parts.append(f"> Pagina {i} non processata.")
        parts.append("")
    return "\n\n---\n\n".join(parts)


def _render_download() -> None:
    states = st.session_state.page_states
    if not states:
        return

    has_pending = any(s == "pending" for s in states)
    help_msg = (
        "Attendere il completamento dell'OCR su tutte le pagine" if has_pending else None
    )

    combined = _build_md_content()

    c1, c2 = st.columns(2)
    c1.download_button(
        "Scarica .md (browser)",
        data=combined.encode("utf-8"),
        file_name="documento.md",
        mime="text/markdown",
        use_container_width=True,
        disabled=has_pending,
        help=help_msg,
    )
    if c2.button(
        "Salva .md nella cartella output",
        type="primary",
        use_container_width=True,
        disabled=has_pending,
        help=help_msg,
    ):
        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_path = Path(st.session_state.output_dir) / f"documento_{ts}.md"
            out_path.write_text(combined, encoding="utf-8")
            try:
                state = _store().load()
                if state:
                    _store().mark_downloaded(state)
            except Exception:  # noqa: BLE001
                logger.exception("mark_downloaded fallito")
            st.success(f"Salvato: `{out_path}`")
            logger.info("Salvato .md: %s", out_path)
        except Exception as e:  # noqa: BLE001
            logger.exception("Save .md fallito")
            st.error(f"Errore salvataggio: {e}")


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

_WATCHDOG_STARTED = False


def main() -> None:
    global _WATCHDOG_STARTED
    st.set_page_config(page_title="GLM-OCR", layout="wide")
    if not _WATCHDOG_STARTED:
        if parent_watchdog.start():
            logger.info("Parent watchdog attivato (psutil)")
        _WATCHDOG_STARTED = True
    _init_state()
    _check_update_on_startup()
    _check_restore_candidate()

    cfg = _render_sidebar()
    _render_update_banner()
    _render_restore_banner()

    # Caricamento file (ignorato se restore_pending attivo, per non sovrascrivere).
    if not st.session_state.restore_pending:
        # L'utente ha tolto il file con la X: svuota la sessione (la preview non
        # deve restare). NON scatta dopo un restore (loaded_via_uploader=False).
        if (not cfg["files"] and st.session_state.loaded_via_uploader
                and st.session_state.file_hash):
            _clear_session()
            st.rerun()
        _ensure_pages_loaded(cfg["files"], cfg["dpi"])

    # Avvio OCR su click.
    if cfg["run_clicked"] and st.session_state.page_states:
        _methods = st.session_state.get("page_methods", [])
        def _is_ocr(i):
            return i >= len(_methods) or _methods[i] == "ocr"
        indices = [i for i, s in enumerate(st.session_state.page_states)
                   if s == "pending" and _is_ocr(i)]
        if not indices:
            indices = [i for i in range(len(st.session_state.page_states)) if _is_ocr(i)]
            for i in indices:
                st.session_state.page_states[i] = "pending"
                st.session_state.ocr_results[i] = None
                st.session_state.ocr_errors[i] = None
        _start_ocr_job(indices, cfg["mode"], cfg["model"], cfg["host"], cfg["workers"])
        st.rerun()

    if cfg["cancel_clicked"] and st.session_state.ocr_job is not None:
        st.session_state.ocr_job.cancel()
        st.session_state.ocr_job = None
        st.session_state.last_run_completed = True
        logger.info("OCR job cancellato dall'utente")
        st.rerun()

    # Progress OCR (fragment auto-refresh).
    _render_ocr_progress_fragment()

    # Prompt errore in parallelo.
    _render_parallel_prompt(cfg)

    # Riepilogo skipped.
    _render_skipped_summary(cfg)

    # Vista a due colonne.
    _render_comparison(cfg)

    # Download / Save.
    st.divider()
    _render_download()


if __name__ == "__main__":
    main()
