"""Logger persistente per l'app. Tutti gli errori vengono scritti su file
con rotazione (5 MB x 3 backup) per consentire debug post-mortem."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_NAME = "glm_ocr"
LOG_FILENAME = "errors.log"
MAX_BYTES = 5_000_000
BACKUP_COUNT = 3


def _install_dir() -> Path:
    """Cartella di installazione (la radice del progetto), ricavata dal path
    di questo file: app/applog.py -> repo root."""
    return Path(__file__).resolve().parent.parent


def logs_dir() -> Path:
    d = _install_dir() / "logs"
    d.mkdir(exist_ok=True)
    return d


def get_logger() -> logging.Logger:
    """Ritorna il logger principale dell'app. Idempotente: una sola
    configurazione anche se chiamato piu volte."""
    logger = logging.getLogger(LOG_NAME)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = False

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    try:
        file_handler = RotatingFileHandler(
            logs_dir() / LOG_FILENAME,
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)
    except Exception as e:  # noqa: BLE001
        # Se il filesystem non collabora (permessi, disco pieno) almeno
        # logghiamo a stderr per non lasciare l'app cieca.
        sys.stderr.write(f"[applog] impossibile aprire file di log: {e}\n")

    return logger
