"""Contenuto della guida mostrata nel modale '?'.
Tenuto in un modulo separato per aggiornarlo facilmente."""

HELP_MARKDOWN = """
### Cos'e' GLM-OCR

Converte **PDF scansionati o immagini** in **markdown pulito** usando il modello
GLM-OCR ospitato in locale tramite Ollama. Nessun dato esce dal tuo PC.

### Cosa serve

Ollama acceso con il modello `glm-ocr` scaricato.
Lo status nella **sidebar** te lo segnala in verde se tutto e' ok, in rosso altrimenti.

### Come si usa (4 passi)

1. **(Opzionale)** Scegli la **cartella di output** dalla sidebar (`Cartella output -> Cambia...`).
   I file `.md` salvati e la cache della sessione finiscono qui.
2. **Carica** uno o piu' file dalla sidebar (PDF e/o immagini PNG/JPG/WEBP).
   Durante il caricamento di PDF grandi vedi una **barra di progresso**.
3. **Scegli** modalita' (Sequenziale o Parallela) e numero di worker.
4. **Clicca "Esegui OCR"**. Vedi una progress bar centrata con la **% di avanzamento**.
   Naviga le pagine con `< Prev` / `Next >`, confronta originale e markdown,
   poi salva o scarica il `.md` finale in fondo.

### Modalita' OCR

- **Sequenziale** *(consigliata)*: una pagina alla volta. Piu' affidabile.
- **Parallela**: piu' pagine in contemporanea. Piu' veloce, ma stressa Ollama.
  Lo slider **"Worker paralleli"** controlla quante pagine vengono elaborate
  contemporaneamente — **puoi cambiarlo anche mentre l'OCR e' in corso**, il
  nuovo valore viene applicato in tempo reale.
  Se una pagina fallisce dopo i retry, l'OCR si mette in pausa e ti chiede
  se annullare o continuare in sequenziale.

### Ripresa sessione

Se chiudi l'app a meta' di un lavoro e la riapri, trovi un banner
**"Sessione precedente trovata"** con bottoni **Ripristina / Scarta**.
La cache vive nella cartella di output che hai scelto (`.glm-ocr-cache/`).
Cliccare **Scarica/Salva .md** NON elimina la cache: la elimina solo il
caricamento di un nuovo file (o il bottone "Pulisci cache" in Diagnostica).

### Gestione errori

Ogni pagina e' ritentata automaticamente **fino a 3 volte**. Se fallisce comunque
puoi:
- cliccare **Riprova** per ritentare manualmente,
- oppure **Skippa** per saltarla e proseguire.

A fine elaborazione, se ci sono pagine saltate, compare un banner con il
bottone **"Riprova OCR sulle pagine skippate"**.

### Log e diagnostica

Tutti gli errori vengono salvati su `logs/errors.log` (rotante 5 MB x 3 backup)
per un eventuale debug futuro. Dalla sidebar `Diagnostica -> Apri cartella log`
puoi aprire la cartella direttamente in Esplora Risorse.

### Aggiornamenti

L'app controlla all'avvio se c'e' una versione piu' recente; in caso, mostra un
banner in alto. Puoi anche forzare il controllo dal bottone **"Controlla
aggiornamenti"** nella sidebar.

### Suggerimenti

- Per documenti con **tabelle complesse**, prova ad alzare il **DPI** a 250-300
  nelle impostazioni (sidebar).
- Per fermare l'app: chiudi la finestra del terminale dove gira.
"""
