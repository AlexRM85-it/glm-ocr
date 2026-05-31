# CLAUDE.md — GLM-OCR

Webapp locale Streamlit: PDF/immagini scansionati → markdown pulito via modello
`glm-ocr` su Ollama locale. Distribuibile come installer .exe (Windows).

## STACK DEL REPO
- Linguaggi: Python 3.14
- Framework/librerie: Streamlit, PyMuPDF (fitz), Pillow, requests, psutil, markitdown
- Package manager: pip + `app/requirements.txt`
- Build/run: `.venv\Scripts\python.exe -m streamlit run app\app.py`
- Test: `.venv\Scripts\python.exe -m pytest tests\ -q` (30 test, ~2s, no Ollama necessario)
- Lint/format: nessuno configurato nel repo
- Struttura rilevante:
    app/        codice versionato (sostituito dagli update) · app.py = UI + orchestrazione
    tests/      pytest
    installer/  bootstrap PowerShell (primo avvio: scarica Python embedded, Ollama, modello)
    release/    build installer + pacchetto update (Inno Setup)
    data/       stato persistente (config, cache OCR, backup) — git-ignored
    logs/       log runtime — git-ignored
    runtime/    Python embedded popolato al primo avvio — git-ignored

## NOTE SPECIFICHE DEL PROGETTO
- OCR result vive SOLO in `st.session_state`: chiudere la scheda lo perde; solo il
  download/salvataggio `.md` persiste. Il restore cross-sessione viene dalla cache in `data/`.
- Apply update: SOLO dal bootstrap, MAI mentre Streamlit gira (race su moduli Python).
- Ollama non viene mai disinstallato (potrebbe servire ad altre app).
- Lingua UI/messaggi: italiano. Codice/log: inglese.
- Driver per avviare/pilotare l'app: skill `/run-glm-ocr-app`
  (`.claude/skills/run-glm-ocr-app/driver.py`, modi `ocr` e `serve`).

## COMANDI UTILI
- Avvia + pilota UI (agente): `.venv\Scripts\python.exe .claude\skills\run-glm-ocr-app\driver.py serve`
- Smoke OCR diretto (no browser): `.venv\Scripts\python.exe .claude\skills\run-glm-ocr-app\driver.py ocr`
- Verifica Ollama: `.venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'app'); import ocr_client; print(ocr_client.check_ollama_available())"`
- Setup venv: `python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r app\requirements.txt`
