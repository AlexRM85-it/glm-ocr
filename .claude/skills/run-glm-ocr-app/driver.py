#!/usr/bin/env python
"""Driver for the GLM-OCR Streamlit app.

Two modes — see SKILL.md for the full agent workflow:

  serve   Launch Streamlit headless on :8501, poll /_stcore/health until ready,
          then block (Ctrl-C to stop). Use this before driving the UI with the
          Playwright MCP browser tools.

  ocr     Direct invocation, NO browser: generate a tiny text image, call the
          internal OCR pipeline (ocr_client.check_ollama_available + ocr_image)
          and assert the transcription contains the expected text. Covers PRs
          that touch app internals. Requires Ollama running with glm-ocr.

Run from the repo root with the venv python:
  .venv\\Scripts\\python.exe .claude\\skills\\run-glm-ocr-app\\driver.py ocr
  .venv\\Scripts\\python.exe .claude\\skills\\run-glm-ocr-app\\driver.py serve
"""
from __future__ import annotations

import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
APP = REPO / "app"
PORT = 8501
HEALTH = f"http://localhost:{PORT}/_stcore/health"


def _health_ok() -> bool:
    try:
        with urllib.request.urlopen(HEALTH, timeout=2) as r:
            return r.status == 200 and r.read().strip() == b"ok"
    except Exception:
        return False


def serve() -> int:
    py = REPO / ".venv" / "Scripts" / "python.exe"
    cmd = [
        str(py), "-m", "streamlit", "run", str(APP / "app.py"),
        "--server.headless", "true",
        "--server.port", str(PORT),
        "--browser.gatherUsageStats", "false",
    ]
    print(f"[driver] launching: {' '.join(cmd)}", flush=True)
    proc = subprocess.Popen(cmd, cwd=str(REPO))
    try:
        for _ in range(60):
            if _health_ok():
                print(f"[driver] READY -> http://localhost:{PORT}", flush=True)
                print("[driver] drive the UI with the Playwright MCP browser tools; Ctrl-C to stop.", flush=True)
                proc.wait()
                return proc.returncode or 0
            time.sleep(1)
        print("[driver] FAILED: health check never passed", file=sys.stderr)
        proc.terminate()
        return 1
    except KeyboardInterrupt:
        proc.terminate()
        return 0


def ocr() -> int:
    # Import the app's own modules (they assume cwd-independent paths).
    sys.path.insert(0, str(APP))
    from PIL import Image, ImageDraw
    import ocr_client

    ok, msg = ocr_client.check_ollama_available()
    print(f"[driver] ollama: {msg}")
    if not ok:
        print("[driver] FAILED: Ollama/glm-ocr not available", file=sys.stderr)
        return 2

    img = Image.new("RGB", (800, 300), "white")
    d = ImageDraw.Draw(img)
    d.text((40, 60), "Hello GLM-OCR", fill="black")
    d.text((40, 120), "Smoke test line 2", fill="black")
    d.text((40, 180), "Numbers 12345", fill="black")

    print("[driver] running OCR (may take ~30s on first call)...")
    text = ocr_client.ocr_image_with_retry(img)
    print("[driver] --- transcription ---")
    print(text)
    print("[driver] ----------------------")
    if "GLM-OCR" not in text and "12345" not in text:
        print("[driver] FAILED: expected text not found in transcription", file=sys.stderr)
        return 1
    print("[driver] OK: transcription contains expected text")
    return 0


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "ocr"
    if mode == "serve":
        return serve()
    if mode == "ocr":
        return ocr()
    print(f"unknown mode: {mode!r} (use 'serve' or 'ocr')", file=sys.stderr)
    return 64


if __name__ == "__main__":
    raise SystemExit(main())
