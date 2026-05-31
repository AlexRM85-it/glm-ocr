# GLM-OCR — Project State

> **Per Claude / dev che apre il progetto:** leggi questo file **PRIMA** di esplorare il codice.
> Contiene contesto, schema architetturale, e backlog. Aggiornato a ogni bump di versione.
> Tutto quello che è in questo file è authoritative — il *perché* non è desumibile dal solo codice.

---

## Versione corrente

- **App version**: `0.4.0` (vedi `app/VERSION`)
- **Ultimo aggiornamento di questo file**: 2026-05-30
- **Stato**: Fase 5 completata — Stage B MarkItDown implementato, validato E2E in browser, artefatti v0.4.0 buildati. Resta solo upload su GitHub Release + cleanup file temp.

> **Fase 5 / v0.4.0 — MarkItDown (Stage B):** i formati Office/Web/dati
> (docx, pptx, xlsx, html, htm, csv, json, xml, epub) vengono convertiti in
> markdown via MarkItDown — NON passano dall'OCR vision. Ogni file genera UNA
> pagina sintetica (sentinella `local_idx == -2` nel page_map, nessuna immagine):
> pannello sx = placeholder info-file, pannello dx = markdown. Nuovo
> `app/markitdown_loader.py`; nuovo method per-pagina `"markitdown"`. Dep
> `markitdown[docx,pptx,xlsx,xls]` aggiunta a requirements (flag updater
> `requirements_changed`). Design doc in
> `docs/superpowers/specs/2026-05-30-stage-b-markitdown-design.md`.

> **Fase 4 / v0.3.0 — text-layer fast-path (Stage A):** i PDF born-digital con
> testo selezionabile vengono ora estratti per-pagina con PyMuPDF (perfetto+
> istantaneo) invece di passare dal modello OCR; GLM-OCR resta solo per le pagine
> scansione/immagine. Nuovo `app/text_extract.py`; nuovo campo per-pagina
> `page_methods` ("text"|"ocr"|"markitdown") in session_state e cache (schema 2,
> retrocompat).
- **Piattaforma supportata**: Windows 10/11 x64 (solo)

---

## Cos'è

Webapp locale (Streamlit) che converte PDF scansionati e immagini in markdown pulito usando il modello **GLM-OCR** ospitato in locale su **Ollama**. Layout side-by-side: documento originale a sinistra, markdown OCR a destra, navigabile pagina per pagina.

Distribuita come **installer `.exe`** (Inno Setup) che al primo avvio scarica e configura automaticamente Python embedded, Ollama, e il modello GLM-OCR. Auto-update da **GitHub Releases**.

Use case primario: utente singolo su Windows che vuole OCR locale (privacy, no cloud) di documenti scansionati.

---

## Stack tecnico

| Componente | Versione | Note |
|------------|----------|------|
| Python | 3.12.7 embedded (prod) / 3.14 (dev) | Embedded non include `tkinter` |
| Streamlit | >= 1.37 | `st.fragment(run_every=...)` per polling progress |
| PyMuPDF (fitz) | >= 1.24 | Rendering PDF, no dipendenza Poppler |
| requests | >= 2.31 | HTTP Ollama `/api/generate` |
| Pillow | >= 10.0 | Manipolazione immagini |
| psutil | >= 5.9 | Watchdog parent process (opzionale, solo se punto 7 lo richiede) |
| Inno Setup | 6.x | Build installer `.exe` |
| MarkItDown | >= 0.1.6 | `markitdown[docx,pptx,xlsx,xls]` — conversione Office/Web/dati → md (Stage B). Tira onnxruntime+magika |
| Ollama | latest | Hostato in locale su `http://localhost:11434` |

---

## Schema architetturale

```
+-----------------------------------------------------------+
| Avvia GLM-OCR.bat -> installer/bootstrap.ps1              |
| (idempotente: Python embedded, pip, Ollama silent, model) |
+-----------------------------------------------------------+
                       v
+-----------------------------------------------------------+
| streamlit run app/app.py                                  |
|   |-- document_loader.py  (PDF/img -> PIL.Image)         |
|   |-- ocr_client.py       (HTTP Ollama, retry x3)        |
|   |-- ocr_job.py          (background dispatcher,         |
|   |                        worker pool ridimensionabile)  |
|   |-- ocr_store.py        (cache OCR cross-session disk) |
|   |-- folder_picker.py    (dialog nativo via PowerShell)  |
|   |-- applog.py           (RotatingFileHandler logger)   |
|   |-- updater.py          (GitHub Releases check/apply)  |
|   `-- help_content.py     (markdown guida modale)         |
+-----------------------------------------------------------+
                       v
+-----------------------------------------------------------+
| File su disco (cartella install):                         |
|   runtime/python/        Python embedded + site-packages |
|   runtime/.requirements_hash  pip install hash tracking  |
|   data/config.json       preferenze utente (output_dir)  |
|   data/backups/          backup app/ pre-update (rolling)|
|   data/update_staging/   update scaricato in attesa apply|
|   data/update_cache.json cache check update (1h TTL)     |
|   logs/bootstrap.log     log del bootstrap PowerShell    |
|   logs/errors.log        log rotante errori app (Python) |
| Cartella scelta dall'utente per output:                   |
|   <output_dir>/.glm-ocr-cache/  cache OCR cross-session  |
|     state.json           manifest sessione                |
|     source_<i>.<ext>     copia file sorgente             |
+-----------------------------------------------------------+
```

---

## Cosa è stato implementato

### Fase 1 — v0.1.0 (completata)
- [x] App Streamlit core con layout a due colonne (originale sx, markdown dx)
- [x] Caricamento PDF multi-pagina via PyMuPDF + immagini PNG/JPG/JPEG/WEBP/BMP/TIFF
- [x] OCR via Ollama `/api/generate` endpoint con base64
- [x] Retry automatico x3 con exponential backoff (`ocr_image_with_retry`)
- [x] Modalità sequenziale + parallela (`ThreadPoolExecutor`)
- [x] Gestione errori: retry/skip per-pagina inline; prompt parallelo→sequenziale al primo errore
- [x] Riepilogo finale pagine skippate + bottone "Riprova OCR sulle pagine skippate"
- [x] Download `.md` finale con placeholder per pagine non processate
- [x] Tab "Renderizzato" / "Sorgente" per il markdown OCR
- [x] Status Ollama (verde/rosso) in sidebar
- [x] Configurazione runtime: host, modello, DPI rendering PDF
- [x] Hash file uploadati per evitare ri-elaborazione su rerun Streamlit

### Fase 2 — v0.1.0 (completata)
- [x] Distribuzione tramite installer `.exe` (Inno Setup `release/setup.iss`)
- [x] Bootstrap PowerShell idempotente (`installer/bootstrap.ps1`):
  - [x] Python embedded download/extract + patch `._pth` per `import site`
  - [x] pip install con tracking hash di `requirements.txt`
  - [x] Ollama silent install (fallback `/SILENT` poi `/S`)
  - [x] `ollama pull glm-ocr:latest`
  - [x] Apply pending update prima di lanciare app
- [x] Auto-update da GitHub Releases (`app/updater.py`):
  - [x] Check con cache 1h, GitHub API rate-limit safe (60/h)
  - [x] Download + stage in `data/update_staging/`
  - [x] Backup rolling di `app/` (max 3) prima di apply
  - [x] Manifest flags: `requirements_changed`, `model.pull_required`
- [x] Modale guida (?) con `@st.dialog`, contenuto in `app/help_content.py`
- [x] Build scripts: `release/build_installer.ps1`, `release/build_update.ps1`
- [x] Manifest template: `release/manifest.template.json`
- [x] Uninstaller con conferma rimozione `data/` (preserva preferenze opzionalmente)
- [x] Generato artefatti v0.1.0 in `dist/`

### Fase 3 — v0.2.0 (codice completato + 3 fix da test E2E in corso, **sospeso al test pag 3**)

**Stato sospensione 2026-05-27:** test E2E in corso su `sample_pages.pdf` (19 pag, prezzario edilizia). Server Streamlit lasciato vivo in background (port 8501, `--server.runOnSave true`). Fix applicati in questa sessione:

1. **Bottoni download .md disabilitati durante OCR** ([app.py:_render_download](app/app.py)): visibili ma grigi con tooltip "Attendere il completamento dell'OCR su tutte le pagine" finché esiste anche una sola pagina in stato `pending`. Verificato OK.
2. **Bug Ripristina cross-session** ([app.py:_ensure_pages_loaded](app/app.py), [_do_restore](app/app.py), [_render_restore_banner](app/app.py)): `OcrStore.save_sources()` non veniva mai chiamato → cache rotta (state.json esisteva ma `source_NNN.pdf` no) → restore falliva silenziosamente. Fix: chiamato `save_sources(files)` dopo `clear()` in `_ensure_pages_loaded`; `_do_restore` ora ritorna `bool`; banner fa `st.rerun()` solo su success così l'`st.error` resta visibile. **Da ri-testare**: nuovo upload → OCR → F5 → Ripristina deve funzionare (cache `.glm-ocr-cache/` deve contenere sia state.json che source_000.pdf).
3. **OCR salta contenuto su layout multi-colonna** (sample_pages.pdf pag 3: modello salta header, top table, intera colonna destra). Fix applicati: prompt più direttivo in [ocr_client.py:OCR_PROMPT](app/ocr_client.py) (reading order esplicito left→right, no-skip, hint lingua IT, no code fence) + DPI default 200 → 300 in [app.py:85](app/app.py#L85). **Da testare**: ri-eseguire OCR su 19 pagine e confrontare output pag 3.

**Mancano (dal piano originale di Fase 3, ancora aperti)**:
- Test verifica chiusura X console → kill server (Punto 7 / parent_watchdog)
- Build artefatti v0.2.0 (`release/build_installer.ps1` + `release/build_update.ps1`)
- Eventuale cleanup `test_phase3.py` (script di test temporaneo nella root)

**Backlog OCR (se A+B non basta)**: D=split colonne (detect + 2 chiamate per pagina), E=cambio modello a VLM più grande (qwen2.5-vl:7b o llama3.2-vision:11b). Vedi memoria engram `glm-ocr/ocr-quality/prompt-and-dpi-tuned-for-multicol`.

- [x] Cache OCR cross-session lazy (`app/ocr_store.py`) — file `.glm-ocr-cache/` nella output_dir
- [x] Selezione cartella output via tkinter dialog OS-native (`app/folder_picker.py`)
- [x] Progress bar caricamento file con % grafica
- [x] Progress OCR % grafica centrata e prominente
- [x] OCR in background thread con worker pool ridimensionabile live (`app/ocr_job.py`)
- [x] Polling UI via `st.fragment(run_every="500ms")`
- [x] Log persistente errori (`app/applog.py` con `RotatingFileHandler`)
- [x] Sostituzione delle `except` silenti con `logger.exception(...)`
- [x] Bottone "Apri cartella log" + "Pulisci cache sessione" in sidebar Diagnostica
- [x] Bottone "Salva .md nella cartella output" affiancato al download browser
- [x] Parent watchdog opzionale (`app/parent_watchdog.py`) basato su psutil
- [x] `PROJECT_STATE.md` (questo file)

---

### Fase 5 — v0.4.0 (Stage B MarkItDown — TDD completato, E2E browser da fare)
- [x] Modulo `app/markitdown_loader.py` (TDD): `SUPPORTED_MARKITDOWN_EXTS`,
  `is_markitdown_ext`, `convert_to_markdown` (tempfile col suffisso giusto +
  lazy-import markitdown). Indipendente da Streamlit.
- [x] Wiring `app/app.py`: sentinella `local_idx == -2` (pagina markitdown,
  no immagine) in `_build_page_map`, `_render_pages_with_progress`, `_get_page`
  (ritorna None); uploader `type=[...]` esteso; nuovo `_apply_markitdown()`
  chiamato dopo `_apply_text_fastpath()`; pannello sx = placeholder info-file;
  `_retry_markitdown_page()` + `_is_markitdown_page()`.
- [x] Su errore conversione: `page_state="error"` + Riprova/Skippa. Skippa su
  pagina markitdown → warning visibile nel `.md` finale (`> ⚠️ Conversione
  MarkItDown fallita per «file»: errore`).
- [x] `markitdown[docx,pptx,xlsx,xls]` in `app/requirements.txt`; VERSION → 0.4.0.
- [x] Test: `tests/test_markitdown_loader.py` (unit) + `tests/test_stage_b_e2e.py`
  (wiring con fake session_state). 23 test verdi.
- [x] **E2E browser** (Playwright su app live 8501, 2026-05-30): docx+xlsx+csv reali →
  3 pagine sintetiche, placeholder info-file a sx, markdown/tabelle a dx, NESSUN OCR;
  export `.md` combinato OK; restore cross-session OK (`-2` ricostruito, md da cache).
  Fixtures in `data/e2e_fixtures/`.
- [x] Build artefatti v0.4.0 (2026-05-30): `dist/glm-ocr-app-v0.4.0.zip` (32.7 KB,
  include markitdown_loader.py) + `manifest.json` (requirements_changed=true,
  pull_required=false) + `GLM-OCR-Setup-v0.4.0.exe` (2.0 MB). Versioni vecchie
  rimosse da `dist/` (solo v0.4.0).
- [x] Release GitHub `v0.4.0` pubblicata su `AlexRM85-it/glm-ocr` con i 3 asset
  (2026-05-30): https://github.com/AlexRM85-it/glm-ocr/releases/tag/v0.4.0
- [x] Repo reso **public** (2026-05-30) → auto-update funzionante. Validato end-to-end:
  `releases/latest` API non-auth ritorna v0.4.0; download asset non-auth = 200;
  manifest parsato OK da `updater.py` (`requests` rileva UTF-8-SIG, BOM innocuo) →
  `requirements_changed=true` letto correttamente. (`build_installer.ps1` + `build_update.ps1 -RequirementsChanged`).

---

## Backlog / idee future (non programmate)

- [ ] Streaming risultati pagina-per-pagina in UI (richiede modifiche server-side oltre Streamlit)
- [ ] Editor markdown post-OCR (es. con `streamlit-quill`)
- [ ] Export multi-formato: HTML, DOCX, JSON strutturato
- [ ] Multi-modello (switch tra glm-ocr e altri VLM disponibili in Ollama)
- [ ] Supporto macOS / Linux (bootstrap PowerShell→bash, installer .pkg/.deb)
- [ ] Firma digitale dell'installer (richiede certificato code-signing a pagamento)
- [ ] Switch lingua UI (IT/EN)
- [ ] Rollback update via UI (oggi solo backup su disco)
- [ ] Cache compressa / cifrata (oggi file plaintext)
- [ ] Sync cache OCR cross-device (es. via cloud storage)
- [ ] OCR via API cloud opzionale (oltre a Ollama locale)
- [ ] Anteprima zoom/pan sull'immagine originale
- [ ] Selezione regione per OCR parziale
- [ ] Confronto diff tra due run OCR (es. dopo cambio DPI)

---

## Decisioni di design importanti (il "perché")

- **PyMuPDF invece di pdf2image**: niente dipendenza esterna Poppler su Windows, install pulita
- **Python embedded invece di PyInstaller**: update incrementali via zip funzionano (sostituisco `app/`); con pyinstaller avrei dovuto ribuildare l'`.exe` ad ogni update
- **Inno Setup invece di NSIS**: script `.iss` più leggibile, custom uninstaller in Pascal Script più semplice
- **Streamlit invece di FastAPI+React**: single-user locale, prototyping veloce, no separation FE/BE da gestire
- **Stato cross-session su disco invece di session_state-only**: requisito utente, F5/crash non devono perdere lavoro
- **Cache "ibrida lazy"** (solo source + state.json, niente PNG renderizzati): peso cache minimo, ripristino istantaneo, rendering on-demand quando l'utente naviga su una pagina
- **Folder picker via PowerShell `FolderBrowserDialog` (non tkinter)**: il Python embedded
  di prod NON include tkinter → con tkinter il bottone "Cambia..." restava disabilitato e
  l'utente doveva incollare il path. Sostituito con `System.Windows.Forms.FolderBrowserDialog`
  lanciato via `subprocess`→powershell (sempre presente su Windows, zero dipendenze, funziona
  sull'embedded). `is_available()` = Windows + powershell nel PATH. Helper testabili
  (`_build_ps_script`, `_parse_result`) in `tests/test_folder_picker.py`.
- **OCR in background thread con dispatcher custom** (no `ThreadPoolExecutor` riusabile): serve `set_max_workers()` live, che TPE non supporta nativamente
- **`st.fragment(run_every=...)` per polling progress**: evita dipendenza esterna `streamlit-autorefresh`
- **Ollama NON disinstallato dall'uninstaller**: potrebbe servire ad altre app sul PC
- **Update apply SOLO durante bootstrap, MAI mentre Streamlit gira**: evita race condition su moduli Python in import
- **`OcrJob` mantenuto in `st.session_state` invece di singleton globale**: ogni sessione browser ha il suo job; pulizia automatica quando la sessione muore
- **Log file `errors.log` rotante (5MB × 3)**: limita la crescita su disco, mantiene history sufficiente per debug
- **Cache file in plaintext**: app single-user locale, no requisito di confidenzialità; debug più semplice
- **Prompt "Continua in sequenziale" MANTENUTO anche con slider live**: scelta esplicita dell'utente — preferisce comunque un prompt al primo errore in parallelo
- **MarkItDown per Office/Web invece di OCR**: docx/xlsx/html/... hanno gia' struttura
  testuale, l'OCR vision sarebbe lento e sbagliato. Convertiti direttamente in md.
- **Sentinella `local_idx == -2` per pagine MarkItDown**: riusa l'infrastruttura
  `page_map`/`page_methods` di Stage A senza un secondo modello dati. `-1`=immagine,
  `>=0`=pagina PDF, `-2`=pagina sintetica markitdown (nessuna immagine sorgente).
- **`markitdown[docx,pptx,xlsx,xls]` (17 pkg) invece di `[all]` (64 pkg)**: `[all]`
  tira Azure/audio/youtube inutili. html/csv/json/xml/epub coperti dal core. L'extra
  Office porta onnxruntime+magika (rilevamento tipo file): footprint accettato.
- **Lazy-import di markitdown dentro `convert_to_markdown`**: l'app deve avviarsi anche
  se la dep manca; l'errore emerge solo alla conversione, gestito (page_state=error).
- **Build update e installer separati**: l'`.exe` è pesante (~2 MB + bootstrap scarica resto), gli update sono leggeri (~15 KB di codice Python). Workflow: rilasci frequenti di solo codice senza dover ridistribuire l'installer

---

## Vincoli e gotchas

- **Python embedded Windows NON include `tkinter`** → risolto NON usando tkinter: il folder
  picker usa `FolderBrowserDialog` via PowerShell (vedi decisione design). Resta il fallback
  text-input se `is_available()` False (non-Windows o powershell assente)
- **Ollama `/api/generate` blocca**: timeout default 300s in `ocr_client.py`, configurabile per pagine grandi
- **GitHub API rate limit non-auth**: 60 chiamate/ora per IP → updater cache check 1h
- **Inno Setup `iscc.exe`**: cercato in 6 path noti (winget `%LOCALAPPDATA%\Programs\Inno Setup 6\`, Program Files, ecc.) — vedi `release/build_installer.ps1`
- **`manifest.json` flags letti dal bootstrap del PROSSIMO avvio**, non immediatamente
- **PowerShell `$Var:` parser bug**: usare `${Var}:` per stringhe con `:` dopo variabile (vedi fix `build_update.ps1:71`)
- **`UploadedFile` di Streamlit è solo in RAM**: per cache cross-session DOBBIAMO copiare i bytes su disco
- **`st.fragment` richiede Streamlit >= 1.37**: il bump dei requirements scatena `pip install` al prossimo bootstrap (flag `requirements_changed`)
- **`st.rerun()` dentro un fragment**: triggera rerun di tutto lo script, non solo del fragment — usare con parsimonia
- **`ThreadPoolExecutor.cancel()` su future non-iniziato funziona, su future già running NO** — `OcrJob` deve usare un dispatcher custom per supportare resize
- **Modello `glm-ocr` ha tag `:latest` di default**: se Ollama aggiorna il tag tra una pull e l'altra, possono cambiare i comportamenti — documentare in release notes eventuali cambi
- **Inno `[Files]` Excludes funziona solo con pattern in stringa unica separati da virgola** (vedi `setup.iss:45-46`)
- **`os.startfile()` solo Windows**: usato per "Apri cartella log/output" — fallback su altri OS se mai supportati
- **Conversione MarkItDown deterministica**: stessi bytes + stessa lib → stesso esito. Il
  "Riprova" su una pagina markitdown raramente cambia (diverso dall'OCR di rete). Su
  errore: error-state → Riprova/Skippa; Skippa scrive un warning nel `.md` finale.
- **`markitdown` tira `onnxruntime` (~13 MB wheel)**: il Python embedded di prod dovra'
  scaricarlo al bootstrap (flag `requirements_changed`) — primo avvio piu' lento dopo l'update.
- **MarkItDown dispatcha sull'estensione del path**: `convert_to_markdown` scrive i bytes in
  un tempfile col suffisso corretto, NON passa uno stream anonimo.

---

## File chiave (per orientarsi rapidamente)

| File | Quando guardarlo |
|------|------------------|
| `app/app.py` | Entry point UI Streamlit, orchestrazione di tutto |
| `app/ocr_job.py` | (da v0.2.0) cuore del processing OCR, dispatcher + worker pool |
| `app/ocr_client.py` | Costanti Ollama, prompt OCR, retry policy |
| `app/markitdown_loader.py` | (da v0.4.0) conversione Office/Web/dati → md (Stage B) |
| `app/ocr_store.py` | (da v0.2.0) persistenza cache cross-session |
| `app/updater.py` | Sistema auto-update GitHub Releases |
| `app/applog.py` | (da v0.2.0) logger persistente |
| `installer/bootstrap.ps1` | Bootstrap idempotente — qui passa TUTTO al primo avvio |
| `installer/ollama_install.ps1` | Helper install + start Ollama |
| `installer/utils.ps1` | Helper PowerShell (download progress, log, hash) |
| `release/setup.iss` | Script Inno Setup |
| `release/build_installer.ps1` | Wrapper iscc.exe |
| `release/build_update.ps1` | Generatore zip + manifest update |
| `app/VERSION` | Single source of truth versione corrente |

---

## Procedura per riprendere il lavoro su una macchina nuova

1. **Leggere questo file (`PROJECT_STATE.md`) per intero**
2. Leggere `README.md` per setup ambiente di sviluppo
3. Verificare/installare:
   - Python 3.12+ (per dev)
   - Ollama in esecuzione + modello `glm-ocr:latest` (`ollama pull glm-ocr:latest`)
   - Inno Setup 6 (per build installer): `winget install JRSoftware.InnoSetup`
4. Setup venv:
   ```powershell
   cd "<project_root>"
   python -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r app\requirements.txt
   ```
5. Lanciare l'app in dev:
   ```powershell
   .\.venv\Scripts\python.exe -m streamlit run app\app.py
   ```
6. Per build release:
   ```powershell
   .\release\build_installer.ps1
   .\release\build_update.ps1 -RequirementsChanged -ModelPullRequired -Notes "..."
   ```
7. **Aggiornare `app/VERSION` e poi aggiornare questo file `PROJECT_STATE.md`** (sposta item da "IN CORSO" a "completata", aggiungi nuova fase IN CORSO se applicabile, aggiungi nuove decisioni/gotchas scoperti)

---

## Convenzione per Claude

All'inizio di una nuova sessione su questa codebase:
1. Leggere `PROJECT_STATE.md` per intero **PRIMA** di qualunque esplorazione codice
2. Trattare "Decisioni di design importanti" e "Vincoli e gotchas" come authoritative
3. Aggiornare questo file alla fine di ogni cambiamento significativo (insieme al bump di `app/VERSION`, o quando si scopre/decide qualcosa di non ovvio)
4. Mantenere il file leggibile in < 5 minuti — riassumere, non duplicare il codice
