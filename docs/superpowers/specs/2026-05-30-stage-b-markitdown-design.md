# Stage B — MarkItDown loader — Design doc

> Data: 2026-05-30 · Versione target: **0.4.0** · Stato: in attesa di approvazione utente
> Riusa l'infrastruttura `page_methods` di Stage A (v0.3.0). Nuovo method = `"markitdown"`.

## 1. Obiettivo

Permettere all'app di caricare formati Office / Web / dati e convertirli in markdown
**senza** passare dal modello OCR vision, usando la libreria [MarkItDown](https://github.com/microsoft/markitdown).

Ogni file non-PDF/non-immagine genera **una pagina sintetica** (nessuna immagine sorgente):
- pannello destro: markdown convertito (subito `success`, niente OCR)
- pannello sinistro: **placeholder info-file** (nome, tipo, dimensione + nota)

## 2. Formati supportati

`.docx`, `.pptx`, `.xlsx`, `.html`, `.htm`, `.csv`, `.json`, `.xml`, `.epub`

**Escluso ZIP** (deciso in brainstorming: output potenzialmente enorme, edge-case rischioso).

## 3. Dipendenza

`markitdown[docx,pptx,xlsx,xls]` — **17 pacchetti** (confermato dall'utente, 2026-05-30).
Include onnxruntime + magika (rilevamento tipo file). html/csv/json/xml/epub coperti
dal core markitdown (beautifulsoup4/lxml già inclusi). Versione core 0.1.x.

- Aggiunta a `app/requirements.txt`.
- Il bootstrap reinstalla via hash di `requirements.txt` → flag updater `requirements_changed`.
- **Lazy-import** dentro `convert_to_markdown`: l'app deve avviarsi anche se la dep manca
  (errore gestito a runtime, non al boot).

## 4. Nuovo modulo `app/markitdown_loader.py` (TDD)

Indipendente da Streamlit (testabile da solo), come `text_extract.py`.

```python
SUPPORTED_MARKITDOWN_EXTS = {
    ".docx", ".pptx", ".xlsx", ".html", ".htm", ".csv", ".json", ".xml", ".epub"
}

def is_markitdown_ext(name: str) -> bool:
    """True se l'estensione del filename è gestita da MarkItDown."""

def convert_to_markdown(file_bytes: bytes, filename: str) -> str:
    """Scrive bytes in un tempfile col suffisso corretto (MarkItDown dispatcha
    sull'estensione), chiama MarkItDown().convert(path).text_content, ritorna
    il markdown. Lazy-import di markitdown dentro la funzione. Solleva un errore
    chiaro se la dep manca o la conversione fallisce."""
```

### Test (TDD, prima dell'impl)
- `is_markitdown_ext`: vero per ogni ext supportata (case-insensitive), falso per `.pdf`/`.png`/sconosciute.
- `convert_to_markdown` su un `.csv` minimale in-memory → markdown con il contenuto (tabella).
- `convert_to_markdown` su `.json` minimale → contenuto presente nell'output.
- `convert_to_markdown` con suffisso ignoto / bytes corrotti → solleva eccezione gestibile.
- (se markitdown non installato in test env: skip condizionale `pytest.importorskip("markitdown")`.)

## 5. Wiring in `app/app.py`

Sentinella `local_idx`: `-1` = immagine, `>= 0` = pagina PDF, **`-2` = pagina markitdown (nessuna immagine)**.

| # | Punto | Riga ~ | Modifica |
|---|-------|--------|----------|
| 1 | `_build_page_map` | 513 | Nuovo branch: `is_markitdown_ext(name)` → `page_map.append((src_idx, -2))`. Ordine branch: PDF → immagine → markitdown → else `ValueError`. |
| 2 | `_render_pages_with_progress` | 530 | Branch markitdown → `pages.append(None)` (nessuna immagine), `done += 1`, update progress. Index-align con page_map. |
| 3 | uploader `type=[...]` | 437 | Estendere con `docx, pptx, xlsx, html, htm, csv, json, xml, epub`. |
| 4 | `_get_page` | 171 | Se `local_idx == -2` → ritorna `None` (NON rendering immagine). |
| 5 | `_render_comparison` pannello sx | 861 | Se `page_map[cur][1] == -2` → placeholder info-file (nome/tipo/size + "Documento convertito con MarkItDown — nessuna anteprima immagine") invece di `st.image`. |
| 6 | nuovo `_apply_markitdown()` | dopo 591 | Chiamato in `_ensure_pages_loaded` **dopo** `_apply_text_fastpath()`. Per ogni flat con `local == -2`: `page_methods[flat] = "markitdown"`, `convert_to_markdown(...)` → `ocr_results[flat]`, `page_states[flat] = "success"`, `ocr_errors[flat] = None`. Su errore conversione: `page_states[flat] = "error"`, messaggio in `ocr_errors[flat]`. |

`_is_ocr` (riga 1007) già esclude i method `!= "ocr"` → le pagine markitdown NON vengono mai
mandate all'OCR (né al run iniziale né al "OCR su tutte"). Nessuna modifica lì.

### Anteprima markdown (decisione utente: opzione c)
Nessun bottone extra: il pannello **destro** già renderizza il markdown convertito
(tab Renderizzato/Sorgente) per le pagine `success`, identico all'output OCR.

### Gestione errore conversione (decisione utente: opzione a)
Conversione markitdown è **deterministica** (stessi bytes → stesso esito; "riprova"
raramente cambia, a differenza dell'OCR di rete). Comportamento:
- 1 tentativo in `_apply_markitdown`. Su errore: `page_state="error"`, `ocr_errors[flat]`
  = messaggio.
- Pannello dx (riga ~880, ramo `state == "error"`) già offre **Riprova** + **Skippa**.
  Per le pagine markitdown il "Riprova" ri-chiama `convert_to_markdown` (nuovo helper
  `_retry_markitdown_page(i)` invece di `_retry_single_page` che fa OCR).
- **Skippa** su pagina markitdown → `page_state="skipped"`. Nel `.md` finale (download
  e "Salva .md") la pagina skipped emette un **blocco warning visibile**, es.:
  `> ⚠️ Conversione MarkItDown fallita per «<nome file>»: <errore>`.
  (Il download .md già inserisce placeholder per pagine non processate — qui il
  placeholder per le markitdown-skipped riporta il warning specifico.)

## 6. Cache / restore

- `page_methods` già persistito (schema 2, Stage A) → nessun cambio schema.
- `_build_page_map` ricostruisce `(src, -2)` al restore (branch del punto 1) → la sentinella
  sopravvive. Il markdown è già in `ocr_results` (cache), quindi **niente re-conversione** al restore.
- Edge: se la dep markitdown sparisce tra una sessione e l'altra, il restore mostra comunque
  il markdown cached (nessuna conversione richiesta). OK.

## 7. Out of scope (questo stage)
- ZIP, formati audio/immagine-OCR-dentro-Office, Azure doc-intelligence.
- Editing del markdown convertito (resta read-only come l'OCR).
- Anteprima immagine per i file Office (esplicitamente: placeholder).

## 8. Versioning & docs
- `app/VERSION` → `0.4.0`.
- Aggiornare `PROJECT_STATE.md`: nuova fase, decisioni (`-2` sentinella, footprint dep),
  gotcha (lazy-import markitdown, onnxruntime nel footprint).
- `release/build_update.ps1 -RequirementsChanged` per il path di update.

## 9. Piano implementazione (post-approvazione)
1. TDD `markitdown_loader.py` (test → impl).
2. Wiring app.py punti 1–6.
3. `requirements.txt` + `VERSION` 0.4.0.
4. E2E: `.docx` + `.xlsx` (1 pagina sintetica ciascuno, markdown a dx, placeholder a sx, no OCR);
   mixed upload (pdf + docx); restore dopo conversione.
5. Aggiornare `PROJECT_STATE.md`. Cleanup file temp (vedi `RESUME_STAGE_B.md`).
