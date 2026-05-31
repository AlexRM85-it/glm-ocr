# dev-state — Skill di sviluppo standard (design)

> Data: 2026-05-31 · Autore: Ale + Claude · Stato: design approvato, pre-implementazione

## Problema

Ogni progetto di sviluppo ha bisogno di due cose ricorrenti, oggi rifatte a mano
e in modo incoerente da repo a repo:

1. **Riprendere il lavoro** dopo una pausa / cambio macchina / nuova sessione AI,
   senza ri-esplorare tutto il codice e senza perdere il *perché* delle decisioni.
2. **Mantenere aggiornata** la spiegazione di cosa è/fa l'app, le istruzioni d'uso,
   e il setup dell'ambiente di sviluppo.

Il progetto GLM-OCR ha risolto questo con tre artefatti (`PROJECT_STATE.md`,
`README.md`, `CLAUDE.md` di progetto) + una convenzione "leggi lo stato prima del
codice, aggiornalo a fine lavoro". Questo spec generalizza quel metodo in una
**skill globale riutilizzabile in ogni progetto**.

## Obiettivo

Skill globale `dev-state` (`~/.claude/skills/dev-state/`) che standardizza:
- generazione/aggiornamento di `PROJECT_STATE.md` (stato authoritative + resume)
- generazione/aggiornamento di `README.md` (onboarding utente + sviluppatore)
- integrazione (non duplicazione) con `CLAUDE.md` di progetto
- enforcement via hook automatici scritti nel progetto

Non-obiettivi (YAGNI):
- non rimpiazza `/init` (built-in) che genera CLAUDE.md — lo integra
- non sincronizza stato su servizi esterni
- non gestisce CI/CD né release engineering (resta nel README/PROJECT_STATE come testo)

## Decisione: memoria — PROJECT_STATE.md è la fonte unica

`PROJECT_STATE.md` versionato in git è **authoritative** per lo stato del repo.

| Criterio | PROJECT_STATE.md (git) | engram / session-memory |
|---|---|---|
| Versionato/diffabile, review in PR | ✅ | ❌ store esterno |
| Leggibile da umano + collaboratori | ✅ | parziale |
| Drift/contraddizioni | ❌ un file, edit deliberato | ✅ rischio noto |
| Sopravvive a cambio macchina | ✅ (clone) | dipende dal sync |

Divisione del lavoro:
- **engram / session-memory** → solo pattern *cross-progetto*, preferenze, recall
  conversazionale ("cosa dicemmo"). NON duplica lo stato del repo.
- Al **checkpoint** la skill può scrivere al massimo **una riga-puntatore** in engram
  (`progetto X: stato aggiornato → PROJECT_STATE.md @<commit>`), mai una copia.
- **Su conflitto vince il file.**

## Decisione: divisione del lavoro tra i file (anti-drift)

Ogni fatto vive in **UN** file; gli altri linkano. Evita la ripetizione che oggi
in GLM-OCR fa comparire gli stessi fatti in tutti e tre i file (drift garantito).

```
CLAUDE.md       STABILE   → stack, comandi build/test/lint, convenzioni; lo genera /init
PROJECT_STATE   EVOLVE    → versione, stato, fasi, decisioni "perché", gotchas, resume
README.md       ON-EVENT  → onboarding utente + sviluppatore (cambia su feature/release)
```

Enforcement del "resume" = una riga nel `CLAUDE.md` (sempre in context), non la skill
(non sempre in context): *"Leggi PROJECT_STATE.md prima di esplorare il codice; invoca
/dev-state."* La skill la inietta in adopt.

## Architettura della skill

Approccio scelto: **A + B** — skill singola a 4 modi + hook automatici.

```
~/.claude/skills/dev-state/
├─ SKILL.md                       router: 4 modi + convenzioni + quando-fire (corto)
├─ templates/
│  ├─ PROJECT_STATE.template.md   stato authoritative (sezioni sotto)
│  ├─ README.template.md          doppio target utente/sviluppatore
│  ├─ CLAUDE.snippet.md           blocco-convenzione da iniettare in CLAUDE.md
│  └─ settings.hooks.json         hook da mergere in .claude/settings.json
└─ references/
   ├─ adopt.md       procedura bootstrap (repo nuovo o esistente riaperto)
   ├─ resume.md      procedura inizio-sessione
   ├─ checkpoint.md  procedura aggiornamento fine-lavoro
   └─ suspend.md     procedura snapshot mid-task
```

SKILL.md resta un router corto; il dettaglio per modo vive in `references/`, caricato
on-demand (l'agente legge solo il reference del modo invocato → meno context).

## I 4 modi

### adopt (un solo modo per new + existing)
Trigger: `/dev-state adopt` · "adotta dev-state" · "bootstrap stato progetto".
Anche: il modo `resume` nota assenza artefatti → propone `adopt`.

Procedura idempotente — aggiunge **solo** i pezzi mancanti:
1. `CLAUDE.md` assente → suggerisci `/init` (built-in) o genera minimale. Non duplica /init.
2. `PROJECT_STATE.md` assente → genera da template. Repo **esistente con codice** →
   pre-compila da stato rilevato (git log, CLAUDE.md, struttura, `app/VERSION` se c'è),
   non vuoto. Repo nuovo → versione `0.1.0`.
3. `README.md` assente o scarno → genera da template.
4. Blocco-convenzione assente in `CLAUDE.md` → inietta `CLAUDE.snippet.md` (skip se già presente).
5. Hook assenti in `.claude/settings.json` → merge `settings.hooks.json`.
6. Commit `chore: bootstrap dev-state`.

Ogni passo skip-se-presente → rilanciabile in sicurezza su repo già parzialmente adottato.

### resume (ciclico, inizio sessione)
Trigger: `/dev-state resume` · "riprendi lavoro" · "dove eravamo". Anche: hook SessionStart.

1. Leggi `PROJECT_STATE.md` **per intero PRIMA** di esplorare il codice.
2. Tratta "Decisioni di design" + "Vincoli e gotchas" come authoritative.
3. engram/session-memory: query **solo** per ciò che non è nel file.
4. Se manca PROJECT_STATE → proponi `adopt`.
5. Mostra all'utente "Stato corrente" + eventuale blocco "Stato sospensione".

### checkpoint (ciclico, fine lavoro pulito)
Trigger: `/dev-state checkpoint` · "aggiorna stato progetto" · "salva checkpoint".
Anche: hook Stop (promemoria passivo).

1. Aggiorna `PROJECT_STATE.md`: sposta item completati, aggiungi fase/decisioni/gotchas
   scoperti, aggiorna sezione versione + `app/VERSION` (o equivalente) se bump.
2. Aggiorna `README.md` se è cambiato qualcosa di user-facing o dev-facing.
3. Tieni il file **leggibile in < 5 min**: riassumi, non duplicare codice.
4. (opzionale) una riga-puntatore in engram.
5. Se esiste un blocco "Stato sospensione" ormai risolto → assorbilo/rimuovilo.

### suspend (ciclico, stop mid-task)
Trigger: `/dev-state suspend` · "sospendi" · "salva la sessione per continuare dopo".

Scrive/sostituisce un blocco `## Stato sospensione <data>` in PROJECT_STATE con:
- cosa sta girando (server/porte/processi in background)
- cosa è già **verificato-OK**
- cosa resta da **ri-testare**
- file:righe toccati
- prossimo step concreto

Differenza da checkpoint: suspend = lavoro **a metà/sporco** (snapshot per ripartire
esatti); checkpoint = lavoro **concluso/coerente** (stato ufficiale pulito).
Coppia tipica: lavori → `suspend` a fine giornata → `resume` domani → finisci → `checkpoint`.

## Hook automatici (B) — scritti da adopt in `.claude/settings.json`

Versionati, inline, **senza path assoluti macchina-specifici** (sopravvivono al clone).

- **SessionStart** → inietta context: *"Progetto con dev-state. Leggi PROJECT_STATE.md
  prima di esplorare il codice. Invoca /dev-state resume per ripartire."*
- **Stop** → promemoria: *"Hai fatto lavoro significativo? Aggiorna PROJECT_STATE.md
  (/dev-state checkpoint) prima di chiudere."*

Comandi `echo` inline → zero file esterni. Assunzione: shell Windows/PowerShell come
i repo di Ale; il template documenta la variante POSIX (`echo` è comunque portabile).

## Template PROJECT_STATE.md — sezioni (project-agnostic)

Generalizzate da GLM-OCR, ma neutre rispetto al dominio:

1. Header "leggi prima" + nota authoritative
2. Versione corrente / Stato / Data ultimo aggiornamento
3. Cos'è (1 paragrafo)
4. Stack tecnico (tabella componente/versione/note)
5. Schema architetturale (diagramma testuale)
6. Cosa è stato implementato (checklist per-fase)
7. Backlog / idee future
8. **Decisioni di design importanti (il "perché")**
9. **Vincoli e gotchas**
10. File chiave (tabella file / quando-guardarlo)
11. Procedura per riprendere il lavoro
12. `[Stato sospensione <data>]` — sezione opzionale, presente solo se sospeso
13. Convenzione per Claude (leggi prima, decisioni authoritative, aggiorna a fine
    lavoro, < 5 min leggibile)

## Template README.md — sezioni

**Per l'utente finale**: cos'è · installazione · uso · aggiornamenti · disinstallazione.
Sezioni installer/distribuzione marcate *opzionali* (non ogni progetto le ha).

**Per lo sviluppatore**: setup ambiente · lancio in sviluppo · struttura progetto ·
build/release · note tecniche.

## Testing / verifica

La skill è prosa + template, non codice eseguibile. Verifica:
1. **adopt su repo finto vuoto** → genera i 3 artefatti + hook + snippet, commit OK.
2. **adopt idempotente** → secondo run non duplica nulla (tutto skip).
3. **adopt su repo esistente** (es. una copia di GLM-OCR senza PROJECT_STATE) →
   pre-compila da stato rilevato.
4. **hook validi** → `.claude/settings.json` resta JSON valido dopo il merge; SessionStart
   e Stop sparano nei test manuali.
5. **resume** → legge il file e riassume senza esplorare codice prima.

## Rischi

- **Hook inline cross-OS**: `echo` è portabile ma la sintassi di quoting in settings.json
  va testata su Windows. Mitigazione: template con esempio testato + nota POSIX.
- **Merge settings.json**: non sovrascrivere hook esistenti dell'utente. Mitigazione:
  merge additivo, skip se un hook dev-state è già presente.
- **Pre-compilazione PROJECT_STATE su repo esistente**: rischio di "inventare" stato non
  vero. Mitigazione: marca le sezioni dedotte come *da verificare*, non come fatto.
- **Doppio promemoria resume** (CLAUDE.md riga + hook SessionStart): ridondanza voluta,
  basso costo; la riga CLAUDE.md è il fallback se gli hook non sono attivi.

## Prossimi step

→ writing-plans: piano di implementazione (creazione file skill + template + reference +
hook, e verifica sui 5 punti di testing).
