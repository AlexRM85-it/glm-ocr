"""Orchestrazione batch dell'OCR: modalita' sequenziale e parallela.

Lavora su una lista di pagine pre-caricate. Il chiamante (app Streamlit)
mantiene gli stati `ocr_results`, `ocr_errors`, `page_states` e li
aggiorna in base al callback `on_result`."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable

from PIL import Image

from ocr_client import DEFAULT_HOST, DEFAULT_MODEL, OcrError, ocr_image_with_retry


# Callback firmati come (page_index, markdown_or_none, error_message_or_none).
ResultCallback = Callable[[int, str | None, str | None], None]
ProgressCallback = Callable[[int, int], None]  # done, total


@dataclass
class ParallelResult:
    """Esito della modalita' parallela.
    Se `failed_index` e' None, tutte le pagine sono state processate."""
    success_indices: list[int] = field(default_factory=list)
    failed_index: int | None = None
    error_message: str | None = None
    pending_indices: list[int] = field(default_factory=list)


def run_sequential(
    pages: list[Image.Image],
    indices: list[int],
    model: str = DEFAULT_MODEL,
    host: str = DEFAULT_HOST,
    on_result: ResultCallback | None = None,
    on_progress: ProgressCallback | None = None,
    max_attempts: int = 3,
) -> None:
    """Processa le pagine indicate in sequenza.
    Su errore (dopo retry interno) marca la pagina come errore e continua."""
    total = len(indices)
    for done, i in enumerate(indices, start=1):
        try:
            md = ocr_image_with_retry(pages[i], model=model, host=host, max_attempts=max_attempts)
            if on_result:
                on_result(i, md, None)
        except OcrError as e:
            if on_result:
                on_result(i, None, str(e))
        except Exception as e:  # noqa: BLE001 — sicurezza UI: nessun crash
            if on_result:
                on_result(i, None, f"Errore inatteso: {e}")
        if on_progress:
            on_progress(done, total)


def run_parallel(
    pages: list[Image.Image],
    indices: list[int],
    model: str = DEFAULT_MODEL,
    host: str = DEFAULT_HOST,
    max_workers: int = 3,
    on_result: ResultCallback | None = None,
    on_progress: ProgressCallback | None = None,
    max_attempts: int = 3,
) -> ParallelResult:
    """Processa in parallelo. Al primo errore definitivo interrompe il batch:
    annulla i future non avviati, attende quelli in volo (riportandone i
    risultati validi) e restituisce un ParallelResult per la decisione utente."""
    result = ParallelResult()
    total = len(indices)
    done = 0

    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as ex:
        future_to_index: dict[Future, int] = {
            ex.submit(
                ocr_image_with_retry,
                pages[i],
                model=model,
                host=host,
                max_attempts=max_attempts,
            ): i
            for i in indices
        }

        first_error: tuple[int, str] | None = None

        for fut in as_completed(future_to_index):
            i = future_to_index[fut]
            try:
                md = fut.result()
                if on_result:
                    on_result(i, md, None)
                result.success_indices.append(i)
            except Exception as e:  # noqa: BLE001
                if first_error is None:
                    first_error = (i, str(e))
                    # Annulla i future non ancora partiti.
                    for f, idx in future_to_index.items():
                        if not f.done() and f is not fut:
                            if f.cancel():
                                # Pagina mai partita: la rimettiamo tra le pending.
                                if idx not in result.pending_indices:
                                    result.pending_indices.append(idx)
                # Se la pagina e' fallita dopo il primo errore, la rimettiamo
                # comunque tra le pending (sara' rigestita).
                elif i not in result.pending_indices and i != first_error[0]:
                    result.pending_indices.append(i)
            finally:
                done += 1
                if on_progress:
                    on_progress(done, total)

        if first_error is not None:
            failed_idx, msg = first_error
            result.failed_index = failed_idx
            result.error_message = msg
            # Le pending in ordine originale, escluso il failed.
            result.pending_indices = [
                i for i in indices
                if i in result.pending_indices and i != failed_idx
            ]

    return result
