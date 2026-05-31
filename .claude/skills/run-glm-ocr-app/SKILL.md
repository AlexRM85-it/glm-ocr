---
name: run-glm-ocr-app
description: Run, launch, serve, screenshot, or smoke-test the GLM-OCR Streamlit app (PDF/image → markdown via local Ollama glm-ocr). Use when asked to start the app, drive its UI, verify an OCR change works, or take a screenshot.
---

# Run GLM-OCR

Local **Streamlit** web app: upload PDFs/images → transcribe to clean Markdown
via the **glm-ocr** model on a local **Ollama** server. Side-by-side view
(original left, markdown right), page-by-page.

Driven two ways — both wrapped by
[.claude/skills/run-glm-ocr-app/driver.py](.claude/skills/run-glm-ocr-app/driver.py):

- **`ocr` mode** — direct invocation, no browser. Generates a text image, runs
  the real OCR pipeline, asserts the transcription. Use this for PRs touching
  app internals (loaders, `ocr_client`, store, updater).
- **`serve` mode** — launch Streamlit headless, then drive the UI with the
  **Playwright MCP** browser tools. Use this for UI changes / screenshots.

> Paths below are relative to the repo root (`<unit>/`). The venv python is
> `.venv\Scripts\python.exe`. Windows / PowerShell.

## Prerequisites

- **Python venv** already present at `.venv` (Python 3.14). If missing:
  ```powershell
  python -m venv .venv
  .\.venv\Scripts\python.exe -m pip install -r app\requirements.txt
  ```
- **Ollama running** with the `glm-ocr` model pulled. Verify:
  ```powershell
  .\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'app'); import ocr_client; print(ocr_client.check_ollama_available())"
  ```
  Expect `(True, 'OK - glm-ocr:latest disponibile')`. If `False`, OCR will fail
  (the UI still loads; the sidebar shows a red status). Start Ollama / `ollama pull glm-ocr`.

## Run (agent path) — direct OCR smoke, no browser

Fastest confidence the OCR pipeline works end-to-end:

```powershell
.\.venv\Scripts\python.exe .claude\skills\run-glm-ocr-app\driver.py ocr
```

Prints the live transcription and exits `0` when it contains the expected text.
First call takes ~30s (model warm-up). Exit `2` = Ollama/model unavailable.

## Run (agent path) — serve + drive the UI

1. Launch headless (blocks once ready; run it in the background):
   ```powershell
   .\.venv\Scripts\python.exe .claude\skills\run-glm-ocr-app\driver.py serve
   ```
   Waits for `http://localhost:8501/_stcore/health` → `ok`, then prints
   `[driver] READY -> http://localhost:8501`.

2. Drive with the **Playwright MCP** browser tools (this is what produced
   [glm-ocr-home.png](.claude/skills/run-glm-ocr-app/glm-ocr-home.png) and
   [glm-ocr-result.png](.claude/skills/run-glm-ocr-app/glm-ocr-result.png)):
   - `browser_navigate` → `http://localhost:8501`
   - `browser_snapshot` (page title flips from `Streamlit` to `GLM-OCR` once rendered)
   - **Upload:** the `<input type=file>` is hidden behind an overlay — do **not**
     click it directly (pointer-intercept timeout). Instead click the dropzone's
     **Upload** button to open the file chooser, then `browser_file_upload` with
     an absolute path. A `.png`/`.pdf` works; generate one with PIL if needed.
   - Click **Esegui OCR** (enabled once a file is loaded).
   - `browser_wait_for` text `Renderizzato` (the success tab) — allow ~120s.
   - `browser_take_screenshot fullPage:true`.

   Screenshots land under `.playwright-mcp/` (or the path you pass).

3. Stop: Ctrl-C the serve process, or kill it:
   ```powershell
   Get-CimInstance Win32_Process -Filter "name like 'python%'" | Where-Object { $_.CommandLine -like '*streamlit*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
   ```

## Run (human path)

```powershell
.\.venv\Scripts\python.exe -m streamlit run app\app.py
```
Opens a browser tab on `http://localhost:8501`. Or double-click
`Avvia GLM-OCR.bat` (runs the full end-user bootstrap). Useless headless — for
agents use `driver.py`.

## Test

```powershell
.\.venv\Scripts\python.exe -m pytest tests\ -q
```
30 tests, ~2s. No Ollama needed (loaders / markitdown / folder-picker only).

## Gotchas

- **Sidebar says "OK - glm-ocr:latest disponibile" only when Ollama is up.** The
  app launches and renders fully regardless; OCR is what breaks without it. So a
  blank-Ollama machine still passes the `serve`/screenshot path — only `ocr`
  mode (and clicking *Esegui OCR*) needs the model.
- **File input is overlay-blocked.** Clicking the file `<input>` by ref times
  out (`intercepts pointer events`). Click the visible **Upload** button to pop
  the chooser, then `browser_file_upload`.
- **OCR result lives only in `session_state`.** Closing the tab loses it; only
  the `.md` download/save persists. Restored sessions come from `data/` cache.
- **driver.py serve blocks** by design (it `proc.wait()`s). Background it; don't
  expect it to return.
- **Port 8501 reuse:** a stale Streamlit holds the port. Kill it (see Stop
  above) before relaunching, or health flips to a different process.
- **`data/`, `logs/`, `runtime/` are git-ignored** and populated at runtime —
  don't commit anything you drop there during a smoke run.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `driver.py ocr` exits 2 | Ollama not reachable on `localhost:11434` or `glm-ocr` not pulled. Start Ollama, `ollama pull glm-ocr`. |
| `serve` "health check never passed" | Streamlit crashed on import. Run the human-path command directly to see the traceback. |
| Playwright click on file input times out | Expected — click the **Upload** button instead (see Gotchas). |
| Empty/blank screenshot | Page not rendered yet. `browser_snapshot` first; wait until title is `GLM-OCR`. |
