"""Job OCR che gira in background con un worker pool dimensione-dinamica.

A differenza di un classico ThreadPoolExecutor (che non supporta `set_max_workers`
a runtime), qui c'e' un thread "dispatcher" che spawna worker on-demand
rispettando il limite corrente. Quando il limite scende, i worker in eccesso
terminano dopo aver completato la pagina in corso. Quando sale, nuovi worker
partono immediatamente sulle pagine ancora in coda.

Modi d'uso (dall'UI Streamlit):
- start: `job = OcrJob(pages, indices, ...)` -> avvia subito.
- polling: ogni rerun del fragment legge `job.progress()` e
  `job.results_snapshot()`.
- live resize: `job.set_max_workers(n)` -> applicato immediatamente.
- pausa su errore (solo modo parallelo): `pause_on_first_error=True` ferma
  il dispatcher al primo errore; l'UI mostra il prompt "Annulla / Continua
  in sequenziale".
- cancel: `job.cancel()` -> ferma il dispatcher, lascia terminare i worker
  in corso. Le pagine non ancora prese restano "pending".
"""

from __future__ import annotations

import collections
import threading
from dataclasses import dataclass
from typing import Callable

from PIL import Image

from applog import get_logger
from ocr_client import DEFAULT_HOST, DEFAULT_MODEL, ocr_image_with_retry


logger = get_logger()


# Callback firmati come (page_index, markdown_or_none, error_message_or_none).
ResultCallback = Callable[[int, "str | None", "str | None"], None]


@dataclass
class JobStatus:
    completed: int
    total: int
    active_workers: int
    max_workers: int
    paused_on_error: bool
    failed_index: int | None
    error_message: str | None
    is_done: bool
    is_cancelled: bool


class OcrJob:
    """Esegue OCR su un set di pagine in background. Thread-safe."""

    def __init__(
        self,
        pages: list[Image.Image],
        indices: list[int],
        model: str = DEFAULT_MODEL,
        host: str = DEFAULT_HOST,
        initial_workers: int = 1,
        max_attempts: int = 3,
        pause_on_first_error: bool = False,
        on_result: ResultCallback | None = None,
    ):
        self._pages = pages
        self._model = model
        self._host = host
        self._max_attempts = max_attempts
        self._pause_on_first_error = pause_on_first_error
        self._on_result = on_result

        # Stato condiviso (proteggi con _lock).
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)

        self._queue: collections.deque[int] = collections.deque(indices)
        self._total = len(indices)
        self._completed = 0
        self._active_workers = 0
        self._max_workers = max(1, min(8, initial_workers))

        self._done_results: dict[int, tuple[str | None, str | None]] = {}
        self._consumed_results: set[int] = set()  # gia' notificati al chiamante

        self._stop = threading.Event()
        self._paused_on_error = False
        self._failed_index: int | None = None
        self._error_message: str | None = None

        # Dispatcher in background.
        self._dispatcher = threading.Thread(
            target=self._run_dispatcher, name="OcrJob-dispatcher", daemon=True
        )
        self._dispatcher.start()

    # ---- public API ---------------------------------------------------------

    def set_max_workers(self, n: int) -> None:
        n = max(1, min(8, int(n)))
        with self._cv:
            if n == self._max_workers:
                return
            self._max_workers = n
            self._cv.notify_all()  # sveglia dispatcher se in attesa
            logger.info("OcrJob: max_workers -> %d", n)

    def cancel(self) -> None:
        with self._cv:
            self._stop.set()
            self._cv.notify_all()
        logger.info("OcrJob: cancel richiesto")

    def resume_in_sequential(self) -> None:
        """Riprende il job dopo un pause_on_first_error, in modo sequenziale.
        Reset del flag pausa + force max_workers=1 + dispara dispatcher."""
        with self._cv:
            self._paused_on_error = False
            self._max_workers = 1
            self._failed_index = None
            self._error_message = None
            self._cv.notify_all()

    def status(self) -> JobStatus:
        with self._lock:
            return JobStatus(
                completed=self._completed,
                total=self._total,
                active_workers=self._active_workers,
                max_workers=self._max_workers,
                paused_on_error=self._paused_on_error,
                failed_index=self._failed_index,
                error_message=self._error_message,
                is_done=self._is_done_locked(),
                is_cancelled=self._stop.is_set(),
            )

    def progress(self) -> tuple[int, int]:
        with self._lock:
            return self._completed, self._total

    def is_done(self) -> bool:
        with self._lock:
            return self._is_done_locked()

    def is_paused_on_error(self) -> bool:
        with self._lock:
            return self._paused_on_error

    def pending_indices(self) -> list[int]:
        with self._lock:
            return list(self._queue)

    def results_snapshot(self) -> dict[int, tuple[str | None, str | None]]:
        """Ritorna i risultati raccolti finora (copia). Usato dall'UI per
        aggiornare le anteprime pagina."""
        with self._lock:
            return dict(self._done_results)

    def drain_new_results(self) -> list[tuple[int, str | None, str | None]]:
        """Ritorna SOLO i risultati nuovi non ancora consumati dal chiamante.
        Marca quelli ritornati come consumati. Pensato per ridurre il lavoro
        ridondante della UI durante il polling."""
        with self._lock:
            new = []
            for idx, (md, err) in self._done_results.items():
                if idx not in self._consumed_results:
                    new.append((idx, md, err))
                    self._consumed_results.add(idx)
            return new

    # ---- internal -----------------------------------------------------------

    def _is_done_locked(self) -> bool:
        # Considera "done" quando tutte le pagine processate o pausa errore o cancel
        if self._stop.is_set() and self._active_workers == 0:
            return True
        if self._paused_on_error and self._active_workers == 0:
            return True
        return self._completed >= self._total

    def _run_dispatcher(self) -> None:
        """Loop principale: spawna worker fino a max_workers, attende quando
        il limite e' saturo o la coda e' vuota."""
        try:
            while not self._stop.is_set():
                with self._cv:
                    # Esci se done.
                    if self._is_done_locked():
                        return
                    # Se in pausa errore, attendi finche' non viene risolto.
                    if self._paused_on_error:
                        # Aspetta che resume o cancel sveglino.
                        if self._active_workers == 0:
                            self._cv.wait()
                            continue
                        else:
                            # Aspetta che i worker in volo finiscano.
                            self._cv.wait()
                            continue
                    # Coda vuota? attendi che i worker in volo finiscano.
                    if not self._queue:
                        if self._active_workers == 0:
                            return  # tutto processato
                        self._cv.wait()
                        continue
                    # Saturo? attendi che si liberi.
                    if self._active_workers >= self._max_workers:
                        self._cv.wait()
                        continue
                    # Spawna un worker su una nuova pagina.
                    idx = self._queue.popleft()
                    self._active_workers += 1

                t = threading.Thread(
                    target=self._worker, args=(idx,), name=f"OcrJob-w{idx}", daemon=True
                )
                t.start()
        except Exception:  # noqa: BLE001
            logger.exception("OcrJob: dispatcher crash")

    def _worker(self, idx: int) -> None:
        md: str | None = None
        err: str | None = None
        try:
            md = ocr_image_with_retry(
                self._pages[idx],
                model=self._model,
                host=self._host,
                max_attempts=self._max_attempts,
            )
        except Exception as e:  # noqa: BLE001
            err = str(e)
            logger.exception("OcrJob: pagina %d errore: %s", idx, e)
        finally:
            with self._cv:
                self._done_results[idx] = (md, err)
                self._completed += 1
                self._active_workers -= 1
                # Notifica chiamante esterno (callback).
                if self._on_result is not None:
                    try:
                        self._on_result(idx, md, err)
                    except Exception:  # noqa: BLE001
                        logger.exception("OcrJob: on_result callback errore")
                # Eventuale pausa al primo errore (modalita' parallela).
                if (
                    err is not None
                    and self._pause_on_first_error
                    and not self._paused_on_error
                ):
                    self._paused_on_error = True
                    self._failed_index = idx
                    self._error_message = err
                    # Niente nuove pagine vengono prelevate (dispatcher controllera').
                self._cv.notify_all()
