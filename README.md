# GLM-OCR Webapp

Webapp locale (Streamlit) che converte PDF scansionati e immagini in markdown pulito usando il modello **GLM-OCR** ospitato in locale su **Ollama**. Layout side-by-side: documento originale a sinistra, markdown OCR a destra, navigabile pagina per pagina.

Distribuibile come **installer .exe** che al primo avvio scarica e configura automaticamente Python embedded, Ollama e il modello GLM-OCR. Aggiornamenti da **GitHub Releases**.

---

## Per l'utente finale

### Installazione

1. Scarica `GLM-OCR-Setup-vX.Y.Z.exe` dalla pagina Releases del repository GitHub.
2. Doppio click → wizard di installazione (default: `%LOCALAPPDATA%\Programs\GLM-OCR\`, non serve essere admin).
3. Alla fine del wizard tieni attiva la spunta **"Avvia GLM-OCR ora"**.
4. **Al primo avvio** si apre una finestra di console nera. Lì vengono scaricati e configurati in sequenza (può richiedere diversi minuti):
   - Runtime Python embedded (~25 MB)
   - Dipendenze Python
   - Ollama (~600 MB)
   - Modello `glm-ocr:latest` (diversi GB)
5. Finito il setup, il browser si apre automaticamente su `http://localhost:8501`.

### Uso

Nell'app:
1. Carica uno o più file dalla sidebar (PDF multi-pagina e/o immagini PNG/JPG/JPEG/WEBP).
2. Scegli la **modalità OCR** (Sequenziale o Parallela).
3. Clicca **Esegui OCR**.
4. Naviga pagina per pagina, confronta originale (sinistra) e markdown (destra).
5. **Scarica documento completo (.md)** dal bottone in fondo.

Per una guida completa, clicca il bottone **❓** in alto nella sidebar.

### Aggiornamenti

L'app controlla automaticamente all'avvio se è disponibile una nuova versione su GitHub. Quando ce n'è una, mostra un banner in alto. Vai nella sidebar → sezione "Aggiornamenti" → **Installa aggiornamento**. Dopo il download, chiudi la finestra del terminale e rilancia `Avvia GLM-OCR.bat`: l'update viene applicato al successivo avvio.

### Disinstallazione

Pannello di Controllo → Programmi → seleziona GLM-OCR → Disinstalla. L'uninstaller chiede se rimuovere anche i dati utente. **Non rimuove Ollama** (potrebbe servire ad altre app).

---

## Per lo sviluppatore

### Setup ambiente di sviluppo

```powershell
cd "c:\Users\Desktop\Desktop\Imparo a programmare\GLM - OCR app"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r app\requirements.txt
```

### Lancio in sviluppo

```powershell
.\.venv\Scripts\python.exe -m streamlit run app\app.py
```

Oppure: doppio click su `Avvia GLM-OCR.bat` (esegue tutto il bootstrap come farebbe l'utente finale).

### Struttura del progetto

```
GLM-OCR app/
├── Avvia GLM-OCR.bat           Entry point per l'utente (chiama bootstrap.ps1)
├── README.md / LICENSE.txt
├── app/                        CODICE VERSIONATO (sostituito dagli update)
│   ├── app.py                  UI Streamlit + orchestrazione
│   ├── document_loader.py      PDF/immagini → PIL.Image
│   ├── ocr_client.py           Client HTTP Ollama (retry x3)
│   ├── markitdown_loader.py    Office/Web/dati → markdown (no OCR)
│   ├── updater.py              Check + download + apply update
│   ├── help_content.py         Markdown della guida (modale "?")
│   ├── requirements.txt
│   └── VERSION
├── installer/                  Script bootstrap (PowerShell)
│   ├── bootstrap.ps1
│   ├── ollama_install.ps1
│   └── utils.ps1
├── release/                    Build degli artefatti di rilascio
│   ├── setup.iss               Script Inno Setup
│   ├── build_installer.ps1     Compila setup.exe
│   ├── build_update.ps1        Genera zip + manifest per update
│   └── manifest.template.json
├── runtime/                    Popolata al primo avvio (Python embedded)
├── data/                       Stato persistente (preferenze, cache update, backup)
└── logs/                       Log del bootstrap
```

### Build di una nuova release

**Prerequisito**: [Inno Setup](https://jrsoftware.org/isdl.php) installato (`iscc.exe` nel PATH).

1. Aggiorna `app/VERSION` con la nuova versione (es. `0.2.0`).
2. Configura il repository GitHub in `app/updater.py` (variabili `GITHUB_OWNER` e `GITHUB_REPO`).
3. Compila l'installer:
   ```powershell
   .\release\build_installer.ps1
   ```
   → genera `dist\GLM-OCR-Setup-v0.2.0.exe`.
4. Genera il pacchetto update:
   ```powershell
   # opzioni:
   # -RequirementsChanged   se requirements.txt e' cambiato
   # -ModelPullRequired -ModelTag 'glm-ocr:v2'   se serve un nuovo pull del modello
   # -Notes 'Bugfix vari'
   .\release\build_update.ps1
   ```
   → genera `dist\glm-ocr-app-v0.2.0.zip` + `dist\manifest.json`.
5. Crea una **GitHub Release** con tag `v0.2.0` e carica come asset i 3 file generati:
   - `GLM-OCR-Setup-v0.2.0.exe`
   - `glm-ocr-app-v0.2.0.zip`
   - `manifest.json`

L'updater dell'app trova automaticamente la release più recente e propone l'aggiornamento ai client esistenti.

### Note tecniche

- **Tutto in `session_state`**: i risultati OCR vivono solo nella sessione browser; chiudere la scheda li perde. Solo il download `.md` li conserva.
- **Apply update**: avviene SOLO dal bootstrap, MAI mentre Streamlit gira (evita race condition sui moduli Python).
- **Backup**: ogni update fa backup di `app/` in `data/backups/`, rolling (max 3 mantenuti).
- **Ollama**: non viene mai disinstallato (anche dall'uninstaller dell'app), perché potrebbe essere usato da altre applicazioni.
