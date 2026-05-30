"""Wrapper attorno a tkinter.filedialog.askdirectory per scegliere la cartella
di output. Funziona perche' l'app gira sullo stesso PC del browser (single-user
locale). Se tkinter non e' disponibile (Python embedded senza tk) ritorna None
e il chiamante fa fallback a text input."""

from __future__ import annotations

from pathlib import Path


def is_available() -> bool:
    """True se tkinter e' importabile. Su Python embedded di default e' False."""
    try:
        import tkinter  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def pick_folder(initialdir: str | Path | None = None) -> str | None:
    """Apre il dialog OS nativo per selezionare una cartella.
    Ritorna il path scelto come stringa, oppure None se l'utente annulla o
    se tkinter non e' disponibile."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:  # noqa: BLE001
        return None

    initial = str(initialdir) if initialdir else None

    root = tk.Tk()
    try:
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askdirectory(
            initialdir=initial,
            title="Seleziona cartella di output per GLM-OCR",
            mustexist=True,
        )
    finally:
        try:
            root.destroy()
        except Exception:  # noqa: BLE001
            pass

    return path or None


def default_output_dir() -> Path:
    """Cartella di default per i .md di output (creata se non esiste)."""
    docs = Path.home() / "Documents"
    if not docs.exists():
        # Su sistemi non-Windows o senza Documents
        docs = Path.home()
    out = docs / "GLM-OCR"
    out.mkdir(parents=True, exist_ok=True)
    return out
