"""Client HTTP minimale per Ollama /api/generate con supporto vision."""

from __future__ import annotations

import time
from dataclasses import dataclass

import requests
from PIL import Image

from document_loader import to_base64_png


DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MODEL = "glm-ocr:latest"

OCR_PROMPT = (
    "You are an OCR engine. Transcribe EVERY visible text element from this "
    "document image into clean Markdown.\n\n"
    "Rules:\n"
    "- Do NOT skip any text. Include page headers, footers, page numbers, "
    "section labels in the margins, table rows, captions, and small print.\n"
    "- For multi-column layouts: read the LEFT column completely from top to "
    "bottom, then the RIGHT column from top to bottom. Never interleave columns.\n"
    "- Preserve tables using Markdown table syntax. Preserve headings (#, ##), "
    "lists, and figure captions.\n"
    "- The document language may be Italian; transcribe accents and symbols "
    "exactly as shown.\n"
    "- Output only the transcribed Markdown. No commentary, no explanations, "
    "no '```' code fences around the whole output."
)


@dataclass
class OcrError(Exception):
    message: str
    attempts: int = 1

    def __str__(self) -> str:
        return self.message


def check_ollama_available(host: str = DEFAULT_HOST, model: str = DEFAULT_MODEL) -> tuple[bool, str]:
    """Verifica che Ollama risponda e che il modello richiesto sia installato.
    Ritorna (ok, messaggio)."""
    url = f"{host.rstrip('/')}/api/tags"
    try:
        r = requests.get(url, timeout=5)
        r.raise_for_status()
    except requests.RequestException as e:
        return False, f"Impossibile contattare Ollama su {host}: {e}"

    data = r.json() or {}
    installed = [m.get("name", "") for m in data.get("models", [])]
    # Tolleranza: confronto sia con nome esatto sia ignorando il tag :latest.
    short = model.split(":", 1)[0]
    if model in installed or any(name.split(":", 1)[0] == short for name in installed):
        return True, f"OK - {model} disponibile"
    return False, (
        f"Modello '{model}' non installato su Ollama.\n"
        f"Modelli trovati: {installed or 'nessuno'}.\n"
        f"Esegui:  ollama pull {model}"
    )


def ocr_image(
    image: Image.Image,
    model: str = DEFAULT_MODEL,
    host: str = DEFAULT_HOST,
    timeout: int = 300,
) -> str:
    """Singola chiamata OCR. Solleva OcrError su qualsiasi problema."""
    url = f"{host.rstrip('/')}/api/generate"
    payload = {
        "model": model,
        "prompt": OCR_PROMPT,
        "images": [to_base64_png(image)],
        "stream": False,
        "options": {"temperature": 0},
    }
    try:
        r = requests.post(url, json=payload, timeout=timeout)
    except requests.RequestException as e:
        raise OcrError(f"Errore di rete: {e}") from e

    if r.status_code != 200:
        body = (r.text or "")[:300]
        raise OcrError(f"HTTP {r.status_code}: {body}")

    try:
        data = r.json()
    except ValueError as e:
        raise OcrError(f"Risposta non JSON: {e}") from e

    text = (data.get("response") or "").strip()
    if not text:
        raise OcrError("Risposta vuota da Ollama")
    return text


def ocr_image_with_retry(
    image: Image.Image,
    model: str = DEFAULT_MODEL,
    host: str = DEFAULT_HOST,
    max_attempts: int = 3,
    base_delay: float = 1.5,
    timeout: int = 300,
) -> str:
    """Wrapper con retry esponenziale (3 tentativi di default).
    Solleva OcrError con riepilogo se tutti i tentativi falliscono."""
    last_err: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return ocr_image(image, model=model, host=host, timeout=timeout)
        except Exception as e:  # noqa: BLE001 — catturo per ritentare
            last_err = e
            if attempt < max_attempts:
                time.sleep(base_delay * (2 ** (attempt - 1)))
    raise OcrError(
        f"Fallito dopo {max_attempts} tentativi: {last_err}",
        attempts=max_attempts,
    )
