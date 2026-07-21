# wikipedia-in-italiano

Progetto per tradurre in italiano pagine di Wikipedia per il training di
OpenEmma.

Le voci da tradurre sono raggruppate in [`groups/`](groups/): ogni file elenca
alcune centinaia di pagine inglesi che non hanno ancora una versione italiana.
Chi contribuisce si prenota un gruppo, lo traduce con l'aiuto di un assistente
AI e apre una pull request.

> **Nota:** lo script di traduzione è in fase di sviluppo — vedi
> [issue #3](https://github.com/OpenEmmaLab/wikipedia-in-italiano/issues/3).
> I comandi di questa guida saranno operativi quando lo script sarà pubblicato.

## Cosa ti serve

Prima di iniziare devi avere tre cose.

### 1. Un account GitHub

Il traduttore lavora **attraverso GitHub**: crea una copia personale (fork) di
questo repository, apre una issue per prenotarsi il gruppo di voci su cui
lavorerai — così due persone non traducono le stesse pagine — e alla fine
propone il tuo lavoro con una pull request.

Se non hai un account, registrati gratuitamente su
[github.com/signup](https://github.com/signup).

Non serve configurare nulla a mano: al primo avvio lo script apre il browser per
farti autorizzare l'accesso e ti chiede di incollare in console un codice che
vedrai sulla pagina.

### 2. Claude Code oppure Codex

La traduzione vera e propria la fa un assistente AI da riga di comando. Devi
averne installato **uno dei due**:

- [Claude Code](https://claude.com/claude-code)
- [Codex](https://developers.openai.com/codex/cli)

Anche qui, se non hai ancora fatto il login, lo script apre il browser e ti
chiede di incollare il codice di autenticazione.

### 3. uv

`uv` è lo strumento che scarica ed esegue lo script Python con tutte le sue
dipendenze, senza che tu debba installare niente a mano. Include il comando
`uvx`, quello che userai per lanciare il traduttore.

**macOS e Linux** — apri il terminale e incolla:

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Su macOS, in alternativa, se usi [Homebrew](https://brew.sh):

```sh
brew install uv
```

**Windows** — apri PowerShell e incolla:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Chiudi e riapri il terminale, poi verifica che l'installazione sia andata a buon
fine:

```sh
uv --version
```

Se il comando non viene trovato, consulta la
[guida ufficiale all'installazione](https://docs.astral.sh/uv/getting-started/installation/).

## Come lanciare il traduttore

Apri il terminale (su Windows: PowerShell) ed esegui:

```sh
uvx --from git+https://github.com/OpenEmmaLab/wikipedia-in-italiano translate
```

Non serve scaricare il repository prima: `uvx` fa tutto da solo.

Al primo avvio lo script ti guiderà attraverso le autenticazioni descritte
sopra. Poi lavorerà da solo:

1. crea (o aggiorna) il tuo fork del repository;
2. sceglie a caso un gruppo di voci ancora libero e lo prenota aprendo una issue;
3. scarica il testo inglese di ogni voce e lo fa tradurre in italiano
   dall'assistente AI;
4. salva le traduzioni e le carica sul tuo fork ogni 10 voci completate;
5. alla fine apre una pull request e chiude la issue di prenotazione.

Il processo è interattivo: lascia il terminale aperto mentre lavora.

### Se si interrompe

Puoi chiudere tutto e rilanciare lo stesso comando più tardi. Il lavoro già
fatto viene salvato su GitHub ogni 10 voci, quindi riprenderà da dove si era
fermato senza ritradurre quello che è già pronto.

## Come sono organizzate le voci

- [`groups/groups.txt`](groups/groups.txt) — l'indice: un gruppo per riga.
- `groups/<nome>.txt` — le voci del gruppo, una per riga, nel formato
  `identificativo` + tabulazione + `titolo inglese`.
- `translations/<nome>/` — le traduzioni prodotte, un file Markdown per voce.

Gli script [`create-wiki-batches.py`](create-wiki-batches.py) e
[`grouping.py`](grouping.py) servono a rigenerare i gruppi dai dump di Wikipedia
e non sono necessari per contribuire alle traduzioni.
