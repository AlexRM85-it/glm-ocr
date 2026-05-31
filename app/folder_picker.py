"""Selezione cartella di output tramite il dialog nativo Windows.

NON usa tkinter (il Python embedded di prod non lo include). Lancia invece un
`FolderBrowserDialog` di System.Windows.Forms via PowerShell (sempre presente su
Windows). L'app gira sullo stesso PC del browser (single-user locale), quindi il
dialog OS-native ha senso.

Se non siamo su Windows o manca PowerShell, `is_available()` ritorna False e il
chiamante fa fallback a un text input dove incollare il path.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def is_available() -> bool:
    """True se possiamo aprire il dialog nativo (Windows + powershell presente)."""
    if os.name != "nt":
        return False
    return shutil.which("powershell") is not None


def _build_ps_script(initialdir: str | None) -> str:
    """Costruisce lo script PowerShell che mostra il FolderBrowserDialog e
    scrive il path scelto su stdout (vuoto se l'utente annulla).

    Un Form TopMost fa da owner cosi' il dialog appare in primo piano."""
    initial = (initialdir or "").replace("'", "''")  # escape quote singole PS
    return (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "$dlg = New-Object System.Windows.Forms.FolderBrowserDialog;"
        "$dlg.Description = 'Seleziona cartella di output per GLM-OCR';"
        "$dlg.ShowNewFolderButton = $true;"
        f"if ('{initial}' -ne '') {{ $dlg.SelectedPath = '{initial}' }}"
        "$owner = New-Object System.Windows.Forms.Form;"
        "$owner.TopMost = $true;"
        "$res = $dlg.ShowDialog($owner);"
        "if ($res -eq [System.Windows.Forms.DialogResult]::OK) "
        "{ [Console]::Out.Write($dlg.SelectedPath) }"
        "$owner.Dispose();"
    )


def _parse_result(stdout: str | None) -> str | None:
    """Normalizza l'output del dialog: path strippato, o None se vuoto/annullato."""
    if not stdout:
        return None
    p = stdout.strip()
    return p or None


def pick_folder(initialdir: str | Path | None = None) -> str | None:
    """Apre il dialog OS-native per selezionare una cartella.
    Ritorna il path scelto come stringa, oppure None se l'utente annulla o se il
    dialog non e' disponibile."""
    if not is_available():
        return None
    script = _build_ps_script(str(initialdir) if initialdir else None)
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass",
             "-Command", script],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except Exception:  # noqa: BLE001 -- mai fatale: fallback a text input
        return None
    return _parse_result(proc.stdout)


def default_output_dir() -> Path:
    """Cartella di default per i .md di output (creata se non esiste)."""
    docs = Path.home() / "Documents"
    if not docs.exists():
        # Su sistemi non-Windows o senza Documents
        docs = Path.home()
    out = docs / "GLM-OCR"
    out.mkdir(parents=True, exist_ok=True)
    return out
