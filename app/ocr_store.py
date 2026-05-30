"""Persistenza della sessione OCR su disco (cross-session).

Cache "ibrida lazy": salviamo solo il manifest `state.json` + una copia dei file
sorgente nella cartella `<output_dir>/.glm-ocr-cache/`. Le pagine renderizzate
(PIL.Image) NON sono persistite: al ripristino il PDF viene riaperto on-demand
quando l'utente naviga su una pagina specifica (vedi `load_pdf_page` in
document_loader). Vantaggi: cache leggera, ripristino istantaneo.

Eventi che cancellano la cache:
- L'utente carica un nuovo file (hash diverso) -> cache vecchia cancellata.
- L'utente clicca "Pulisci cache" esplicitamente.
Lo scarico del .md NON cancella la cache (l'utente puo' continuare a lavorare).
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CACHE_DIR_NAME = ".glm-ocr-cache"
STATE_FILENAME = "state.json"
SOURCE_PREFIX = "source_"
SCHEMA_VERSION = 2


@dataclass
class SourceFileMeta:
    name: str
    size: int
    stored_as: str  # nome del file copiato dentro la cache


@dataclass
class SessionState:
    schema: int = SCHEMA_VERSION
    created_at: str = ""
    updated_at: str = ""
    file_hash: str = ""
    source_files: list[SourceFileMeta] = field(default_factory=list)
    pdf_dpi: int = 200
    pages_count: int = 0
    page_states: list[str] = field(default_factory=list)
    ocr_results: list[str | None] = field(default_factory=list)
    ocr_errors: list[str | None] = field(default_factory=list)
    current_page: int = 0
    downloaded_at: str | None = None
    page_methods: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["source_files"] = [asdict(s) for s in self.source_files]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SessionState":
        sources = [SourceFileMeta(**s) for s in d.get("source_files", [])]
        return cls(
            schema=d.get("schema", SCHEMA_VERSION),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
            file_hash=d.get("file_hash", ""),
            source_files=sources,
            pdf_dpi=d.get("pdf_dpi", 200),
            pages_count=d.get("pages_count", 0),
            page_states=d.get("page_states", []),
            ocr_results=d.get("ocr_results", []),
            ocr_errors=d.get("ocr_errors", []),
            current_page=d.get("current_page", 0),
            downloaded_at=d.get("downloaded_at"),
            page_methods=d.get("page_methods", []),
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class OcrStore:
    """Manager della cartella `.glm-ocr-cache/` dentro una `output_dir`."""

    def __init__(self, output_dir: str | Path):
        self.output_dir = Path(output_dir)
        self.cache_dir = self.output_dir / CACHE_DIR_NAME
        self.state_file = self.cache_dir / STATE_FILENAME

    # ---- existence / load ---------------------------------------------------

    def exists(self) -> bool:
        return self.state_file.is_file()

    def load(self) -> SessionState | None:
        if not self.exists():
            return None
        try:
            with self.state_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return SessionState.from_dict(data)
        except Exception:  # noqa: BLE001
            # File corrotto -> trattiamo come assente.
            return None

    # ---- save ---------------------------------------------------------------

    def _ensure_dir(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def save(self, state: SessionState) -> None:
        """Write atomico: scrivi su .tmp e rinomina."""
        self._ensure_dir()
        if not state.created_at:
            state.created_at = _now_iso()
        state.updated_at = _now_iso()

        tmp = self.state_file.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(state.to_dict(), f, ensure_ascii=False, indent=2)
        tmp.replace(self.state_file)

    def save_sources(self, files: list) -> list[SourceFileMeta]:
        """Copia i file sorgente nella cache. Accetta UploadedFile di Streamlit
        o oggetti con `.name`, `.read()`, `.size`. Ritorna i metadata da salvare
        in `state.source_files`."""
        self._ensure_dir()
        # Pulisci eventuali source_* precedenti.
        for old in self.cache_dir.glob(f"{SOURCE_PREFIX}*"):
            try:
                old.unlink()
            except Exception:  # noqa: BLE001
                pass

        metas: list[SourceFileMeta] = []
        for i, f in enumerate(files):
            name = getattr(f, "name", f"file_{i}") or f"file_{i}"
            suffix = Path(name).suffix.lower() or ".bin"
            stored = f"{SOURCE_PREFIX}{i:03d}{suffix}"
            dest = self.cache_dir / stored

            if hasattr(f, "read"):
                if hasattr(f, "seek"):
                    f.seek(0)
                data = f.read()
                if hasattr(f, "seek"):
                    f.seek(0)
            else:
                data = bytes(f)

            dest.write_bytes(data)
            metas.append(SourceFileMeta(name=name, size=len(data), stored_as=stored))
        return metas

    # ---- load sources back --------------------------------------------------

    def source_paths(self, state: SessionState) -> list[Path]:
        return [self.cache_dir / s.stored_as for s in state.source_files]

    def load_source_bytes(self, state: SessionState) -> list[tuple[str, bytes]]:
        """Ritorna [(filename_originale, bytes), ...] per ricostruire le
        pagine al ripristino."""
        result = []
        for meta in state.source_files:
            p = self.cache_dir / meta.stored_as
            if not p.exists():
                continue
            result.append((meta.name, p.read_bytes()))
        return result

    # ---- mark downloaded ----------------------------------------------------

    def mark_downloaded(self, state: SessionState) -> None:
        state.downloaded_at = _now_iso()
        self.save(state)

    # ---- clear --------------------------------------------------------------

    def clear(self) -> None:
        """Rimuove l'intera cartella cache."""
        if self.cache_dir.exists():
            try:
                shutil.rmtree(self.cache_dir)
            except Exception:  # noqa: BLE001
                pass

    # ---- info per UI banner -------------------------------------------------

    def describe(self, state: SessionState) -> str:
        """Stringa human-readable per il banner 'sessione trovata'."""
        names = ", ".join(s.name for s in state.source_files) or "(nessun file)"
        done = sum(1 for s in state.page_states if s == "success")
        total = state.pages_count
        return f"{names} - {done}/{total} pagine processate (ultimo update: {state.updated_at})"
