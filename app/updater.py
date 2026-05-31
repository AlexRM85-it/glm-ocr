"""Sistema di aggiornamento via GitHub Releases.

Flusso:
1. check_for_updates() -> chiama l'API GitHub, confronta con VERSION
2. download_and_stage() -> scarica zip+manifest in data/update_staging/<ver>/
3. apply_pending_update() -> invocato dal bootstrap.ps1 prima dell'avvio app
   (l'apply NON avviene mai mentre l'app gira: troppo rischioso).
"""

from __future__ import annotations

import json
import re
import shutil
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import requests


# --- Configurazione GitHub ---
GITHUB_OWNER = "AlexRM85-it"
GITHUB_REPO = "glm-ocr"

CHECK_CACHE_TTL_SECONDS = 60 * 60  # 1 ora

# --- Percorsi (calcolati relativi alla install dir, padre di app/) ---
APP_DIR = Path(__file__).resolve().parent
INSTALL_DIR = APP_DIR.parent
DATA_DIR = INSTALL_DIR / "data"
STAGING_DIR = DATA_DIR / "update_staging"
BACKUP_DIR = DATA_DIR / "backups"
CACHE_FILE = DATA_DIR / "update_cache.json"
VERSION_FILE = APP_DIR / "VERSION"

# Flag-file letti dal bootstrap per sapere cosa rifare dopo un apply.
FORCE_PIP_FLAG = INSTALL_DIR / "runtime" / ".force_pip_install"
FORCE_MODEL_PULL_FLAG = DATA_DIR / ".force_model_pull"


@dataclass
class UpdateInfo:
    version: str
    notes: str
    zip_url: str
    zip_name: str
    manifest_url: str | None
    requirements_changed: bool = False
    model_pull_required: bool = False
    model_tag: str | None = None


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def is_configured() -> bool:
    """True se GITHUB_OWNER/REPO sono stati personalizzati."""
    return GITHUB_OWNER != "OWNER_PLACEHOLDER" and GITHUB_REPO != "REPO_PLACEHOLDER"


def current_version() -> str:
    try:
        return VERSION_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return "0.0.0"


def _semver_tuple(v: str) -> tuple[int, ...]:
    """Converte '0.2.0' o 'v0.2.0' in (0, 2, 0). Versioni non-semver -> (0,)."""
    v = v.lstrip("vV").strip()
    parts = re.split(r"[.\-+]", v)
    out: list[int] = []
    for p in parts:
        if p.isdigit():
            out.append(int(p))
        else:
            break
    return tuple(out) if out else (0,)


def _is_newer(latest: str, current: str) -> bool:
    return _semver_tuple(latest) > _semver_tuple(current)


def _read_cache() -> dict:
    if not CACHE_FILE.exists():
        return {}
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_cache(data: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


# -----------------------------------------------------------------------------
# Check
# -----------------------------------------------------------------------------

def check_for_updates(force: bool = False, timeout: float = 3.0) -> UpdateInfo | None:
    """Interroga GitHub. Ritorna UpdateInfo se c'e' una versione piu' nuova,
    altrimenti None. Silenzioso su errori di rete (l'app deve funzionare offline)."""
    if not is_configured():
        return None

    cache = _read_cache()
    now = time.time()
    if not force and (now - cache.get("last_check_ts", 0)) < CHECK_CACHE_TTL_SECONDS:
        cached_latest = cache.get("latest_seen")
        if cached_latest and _is_newer(cached_latest, current_version()):
            # Ricostruisco un UpdateInfo "minimale" dalla cache.
            return UpdateInfo(
                version=cached_latest,
                notes=cache.get("latest_notes", ""),
                zip_url=cache.get("latest_zip_url", ""),
                zip_name=cache.get("latest_zip_name", ""),
                manifest_url=cache.get("latest_manifest_url"),
                requirements_changed=cache.get("latest_requirements_changed", False),
                model_pull_required=cache.get("latest_model_pull_required", False),
                model_tag=cache.get("latest_model_tag"),
            )
        return None

    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
    try:
        r = requests.get(url, timeout=timeout, headers={"Accept": "application/vnd.github+json"})
        r.raise_for_status()
        data = r.json()
    except requests.RequestException:
        return None

    tag = (data.get("tag_name") or "").lstrip("vV")
    if not tag:
        return None

    assets = data.get("assets") or []
    zip_asset = next((a for a in assets if a.get("name", "").startswith("glm-ocr-app-v") and a["name"].endswith(".zip")), None)
    manifest_asset = next((a for a in assets if a.get("name") == "manifest.json"), None)

    if not zip_asset:
        # Release non valida per l'auto-update.
        return None

    requirements_changed = False
    model_pull_required = False
    model_tag = None
    notes = data.get("body", "") or ""

    if manifest_asset:
        try:
            mr = requests.get(manifest_asset["browser_download_url"], timeout=timeout)
            mr.raise_for_status()
            mf = mr.json()
            requirements_changed = bool(mf.get("requirements_changed", False))
            mdl = mf.get("model") or {}
            model_pull_required = bool(mdl.get("pull_required", False))
            model_tag = mdl.get("tag")
            notes = mf.get("notes") or notes
        except (requests.RequestException, ValueError):
            pass

    info = UpdateInfo(
        version=tag,
        notes=notes,
        zip_url=zip_asset["browser_download_url"],
        zip_name=zip_asset["name"],
        manifest_url=manifest_asset["browser_download_url"] if manifest_asset else None,
        requirements_changed=requirements_changed,
        model_pull_required=model_pull_required,
        model_tag=model_tag,
    )

    _write_cache({
        "last_check_ts": now,
        "last_check_iso": datetime.now(timezone.utc).isoformat(),
        "latest_seen": info.version,
        "latest_notes": info.notes,
        "latest_zip_url": info.zip_url,
        "latest_zip_name": info.zip_name,
        "latest_manifest_url": info.manifest_url,
        "latest_requirements_changed": info.requirements_changed,
        "latest_model_pull_required": info.model_pull_required,
        "latest_model_tag": info.model_tag,
    })

    return info if _is_newer(info.version, current_version()) else None


# -----------------------------------------------------------------------------
# Download + stage
# -----------------------------------------------------------------------------

ProgressCb = Callable[[int, int | None], None]  # downloaded, total_or_none


def download_and_stage(info: UpdateInfo, on_progress: ProgressCb | None = None) -> Path:
    """Scarica zip + manifest in data/update_staging/<version>/. Al termine crea
    il file READY che segnala al prossimo bootstrap di applicare l'update.
    Ritorna la directory di staging."""
    staging = STAGING_DIR / info.version
    staging.mkdir(parents=True, exist_ok=True)

    zip_path = staging / info.zip_name
    _download_file(info.zip_url, zip_path, on_progress)

    # Verifica che lo zip sia un archivio valido
    if not zipfile.is_zipfile(zip_path):
        zip_path.unlink(missing_ok=True)
        raise RuntimeError(f"Lo zip scaricato ({info.zip_name}) non e' un archivio valido.")

    # Manifest opzionale
    if info.manifest_url:
        try:
            _download_file(info.manifest_url, staging / "manifest.json", None)
        except requests.RequestException:
            pass

    # Sentinel: segnala al prossimo bootstrap che c'e' un update pronto.
    (staging / "READY").write_text(info.version, encoding="utf-8")
    return staging


def _download_file(url: str, dest: Path, on_progress: ProgressCb | None) -> None:
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length", 0)) or None
        downloaded = 0
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                f.write(chunk)
                downloaded += len(chunk)
                if on_progress:
                    on_progress(downloaded, total)


def pending_update_version() -> str | None:
    """Se c'e' un update gia' scaricato e pronto, ritorna la versione."""
    if not STAGING_DIR.exists():
        return None
    versions = []
    for d in STAGING_DIR.iterdir():
        if d.is_dir() and (d / "READY").exists():
            versions.append(d.name)
    if not versions:
        return None
    versions.sort(key=_semver_tuple, reverse=True)
    return versions[0]


# -----------------------------------------------------------------------------
# Apply (chiamato dal bootstrap, NON dall'app live)
# -----------------------------------------------------------------------------

def apply_pending_update() -> bool:
    """Applica l'update piu' recente in staging, se presente. Ritorna True se
    qualcosa e' stato applicato. Idempotente: se non c'e' nulla in staging,
    ritorna False senza errori."""
    version = pending_update_version()
    if not version:
        return False

    staging = STAGING_DIR / version
    zip_files = list(staging.glob("glm-ocr-app-v*.zip"))
    if not zip_files:
        # Cleanup di uno staging incompleto.
        shutil.rmtree(staging, ignore_errors=True)
        return False
    zip_path = zip_files[0]

    # Backup app/ corrente
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup_zip = BACKUP_DIR / f"app_{current_version()}_{int(time.time())}.zip"
    _zip_directory(APP_DIR, backup_zip)
    _rotate_backups(BACKUP_DIR, keep=3)

    # Leggi manifest per i flag post-apply
    manifest_path = staging / "manifest.json"
    requirements_changed = False
    model_pull_required = False
    model_tag = None
    if manifest_path.exists():
        try:
            mf = json.loads(manifest_path.read_text(encoding="utf-8"))
            requirements_changed = bool(mf.get("requirements_changed", False))
            mdl = mf.get("model") or {}
            model_pull_required = bool(mdl.get("pull_required", False))
            model_tag = mdl.get("tag")
        except (json.JSONDecodeError, OSError):
            pass

    # Estrazione sopra app/ (l'updater package ha alla root VERSION, app.py, ecc.)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(APP_DIR)

    # Imposta flag per il bootstrap
    if requirements_changed:
        FORCE_PIP_FLAG.parent.mkdir(parents=True, exist_ok=True)
        FORCE_PIP_FLAG.write_text("1", encoding="utf-8")
    if model_pull_required and model_tag:
        FORCE_MODEL_PULL_FLAG.parent.mkdir(parents=True, exist_ok=True)
        FORCE_MODEL_PULL_FLAG.write_text(model_tag, encoding="utf-8")

    # Cleanup staging
    shutil.rmtree(staging, ignore_errors=True)
    return True


def _zip_directory(src: Path, dest_zip: Path) -> None:
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in src.rglob("*"):
            if p.is_file():
                zf.write(p, arcname=p.relative_to(src))


def _rotate_backups(dir_: Path, keep: int) -> None:
    backups = sorted(dir_.glob("app_*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[keep:]:
        old.unlink(missing_ok=True)


# -----------------------------------------------------------------------------
# CLI entry point (usato dal bootstrap: python -m updater apply)
# -----------------------------------------------------------------------------

def _main(argv: list[str]) -> int:
    if not argv:
        print("Usage: updater.py [apply|check|version]")
        return 1
    cmd = argv[0]
    if cmd == "apply":
        applied = apply_pending_update()
        print("applied" if applied else "no pending update")
        return 0
    if cmd == "check":
        info = check_for_updates(force=True)
        if info:
            print(f"update available: {info.version}")
        else:
            print("no update")
        return 0
    if cmd == "version":
        print(current_version())
        return 0
    print(f"Unknown command: {cmd}")
    return 1


if __name__ == "__main__":
    import sys
    sys.exit(_main(sys.argv[1:]))
