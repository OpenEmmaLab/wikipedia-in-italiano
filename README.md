# wikipedia-in-italiano

Progetto per tradurre in italiano pagine di Wikipedia per il training di
OpenEmma.

Le voci da tradurre sono raggruppate in [`groups/`](groups/): ogni file elenca
alcune centinaia di pagine inglesi che non hanno ancora una versione italiana.
Chi contribuisce si prenota un gruppo, lo traduce con l'aiuto di un assistente
AI e apre una pull request.

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
vedrai sulla pagina. Senza questa autorizzazione lo script non può procedere e
si ferma.

### 2. Claude Code oppure Codex

La traduzione vera e propria la fa un assistente AI da riga di comando. Devi
averne installato **uno dei due**:

- [Claude Code](https://claude.com/claude-code)
- [Codex](https://developers.openai.com/codex/cli)

Anche qui, se non hai ancora fatto il login, lo script apre il browser e ti
chiede di incollare il codice di autenticazione. Prima di iniziare a lavorare fa
una domanda di prova all'assistente: se non risponde, si ferma senza prenotare
nessun gruppo.

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
git clone https://github.com/OpenEmmaLab/wikipedia-in-italiano.git
cd wikipedia-in-italiano
./traduci.py
```

`uv` scarica da solo le librerie che servono: non devi installare nulla a mano.

Se preferisci lavorare su un gruppo preciso invece che su uno scelto a caso:

```sh
./traduci.py --group 0001-0
```

Un gruppo vero contiene circa mille voci e la traduzione richiede parecchie ore.
Per fare una prova ci sono nove gruppi ridotti, da `test1` a `test9`, con una
voce per `test1` fino a nove per `test9`:

```sh
./traduci.py --group test1
```

Al primo avvio lo script ti guiderà attraverso le autenticazioni descritte
sopra. Poi lavorerà da solo:

1. crea il tuo fork del repository e lo clona in `~/.wikipedia-in-italiano`;
2. sceglie a caso un gruppo di voci ancora libero e lo prenota aprendo una issue;
3. scarica tutte le voci del gruppo, le converte in markdown e le pubblica sul
   tuo fork: a questo punto sono ancora in inglese;
4. le fa tradurre una a una dall'assistente AI, caricandole ogni 10 voci;
5. alla fine apre una pull request e chiude la issue di prenotazione;
6. ti propone di annunciare il contributo su LinkedIn e X. È facoltativo: se
   accetti, apre il browser con il testo del post già pronto, che puoi rivedere
   prima di pubblicarlo. Lo script non pubblica nulla al posto tuo.

Il processo è interattivo: lascia il terminale aperto mentre lavora.

### Se si interrompe

Puoi chiudere tutto e rilanciare lo stesso comando più tardi. Il lavoro già
fatto viene salvato su GitHub ogni 10 voci, quindi riprenderà da dove si era
fermato senza ritradurre quello che è già pronto: riconosce il gruppo su cui
stavi lavorando e continua con quello, senza prenderne uno nuovo.

## Come sono organizzate le voci

- [`groups/groups.txt`](groups/groups.txt) — l'indice: un gruppo per riga.
- `groups/<nome>.txt` — le voci del gruppo, una per riga, nel formato
  `identificativo` + tabulazione + `titolo inglese`.
- `groups/test1.txt` … `groups/test9.txt` — gruppi ridotti per le prove, da una
  a nove voci. Non compaiono nell'indice: si raggiungono solo con `--group`.
- `traduzioni/<nome>/` — le traduzioni prodotte, un file Markdown per voce,
  nominato con l'identificativo numerico della pagina.
- `traduzioni/<nome>/translated.txt` — l'elenco delle voci già tradotte, un
  identificativo per riga. È quello che permette allo script di riprendere il
  lavoro senza rifare quanto è già pronto.

## Il codice

- [`traduci.py`](traduci.py) — lo script da lanciare, con il flusso completo.
- [`wikitradus/extract.py`](wikitradus/extract.py) — scarica una voce da
  Wikipedia e la converte in markdown, scartando quel che non è prosa
  dell'articolo (infobox, avvisi, navigazione, bibliografia, immagini).
- [`wikitradus/translate.py`](wikitradus/translate.py) — le due fasi:
  estrazione di tutte le voci del gruppo, poi traduzione una a una.
- [`wikitradus/cli.py`](wikitradus/cli.py) — verifica che `claude` o `codex`
  rispondano davvero, e che tu sia autenticato su GitHub.
- [`wikitradus/repo.py`](wikitradus/repo.py) — fork, clone, branch, issue e
  pull request.

Gli script [`create-wiki-batches.py`](create-wiki-batches.py) e
[`grouping.py`](grouping.py) servono a rigenerare i gruppi dai dump di Wikipedia
e non sono necessari per contribuire alle traduzioni.
