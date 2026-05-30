"""Cintura di sicurezza: se il processo genitore (la console che ha lanciato
streamlit) muore senza propagare il segnale di chiusura, killiamo noi stessi.

Su Windows la chiusura della console con la X dovrebbe gia' propagare
CTRL_CLOSE_EVENT al child python.exe -> Streamlit si spegne. Questo modulo
e' un fallback per gli edge case (es. console killata con taskkill).

E' opzionale: se `psutil` non e' installato, la funzione e' no-op."""

from __future__ import annotations

import os
import threading
import time


def start() -> bool:
    """Avvia un thread daemon che killa il processo se il parent muore.
    Ritorna True se attivato, False se psutil non e' installato."""
    try:
        import psutil
    except ImportError:
        return False

    def _watch() -> None:
        try:
            ppid = os.getppid()
            parent = psutil.Process(ppid)
        except Exception:
            return
        while True:
            try:
                if not parent.is_running() or parent.status() == psutil.STATUS_ZOMBIE:
                    os._exit(0)
            except psutil.NoSuchProcess:
                os._exit(0)
            except Exception:
                pass
            time.sleep(2)

    threading.Thread(target=_watch, name="parent-watchdog", daemon=True).start()
    return True
