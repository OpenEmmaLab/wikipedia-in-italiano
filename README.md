# wikipedia-in-italiano

Progetto per tradurre in italiano pagine di Wikipedia per il training di
OpenEmma.

Le voci da tradurre sono raggruppate in [`groups/`](groups/): ogni file elenca
alcune centinaia di pagine inglesi che non hanno ancora una versione italiana.
Chi contribuisce si prenota un gruppo, lo traduce con l'aiuto di un assistente
AI e apre una pull request.

## Cosa ti serve

Prima di iniziare devi avere quattro cose. Se ne manca qualcuna non è un
problema: lo script se ne accorge al primo avvio e ti stampa i comandi da
eseguire per il tuo sistema operativo.

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

### 2. git e gh

Lo script usa `git` per gestire il tuo lavoro e `gh` (la riga di comando di
GitHub) per creare il fork, aprire la issue e proporre la pull request.

**Windows** — apri PowerShell e incolla:

```powershell
winget install --id Git.Git -e --source winget
winget install --id GitHub.cli -e --source winget
```

`winget` è il gestore di pacchetti di Windows: è già presente su Windows 11 e
sulle versioni recenti di Windows 10. Se non ce l'hai, scarica gli installatori
da [git-scm.com/install/windows](https://git-scm.com/install/windows) e
[cli.github.com](https://cli.github.com).

Chiudi e riapri il terminale al termine, altrimenti i comandi nuovi non vengono
trovati.

**macOS** — `git` di solito c'è già; per `gh` serve
[Homebrew](https://brew.sh):

```sh
brew install gh
```

**Linux** — `git` è quasi sempre preinstallato; per `gh` segui le
[istruzioni ufficiali](https://github.com/cli/cli/blob/trunk/docs/install_linux.md)
per la tua distribuzione. Su Debian e Ubuntu:

```sh
sudo apt install git gh
```

Verifica che siano raggiungibili:

```sh
git --version
gh --version
```

### 3. Claude Code oppure Codex

La traduzione vera e propria la fa un assistente AI da riga di comando. Devi
averne installato **uno dei due**:

- [Claude Code](https://claude.com/claude-code)
- [Codex](https://developers.openai.com/codex/cli)

Prima di iniziare a lavorare lo script fa una domanda di prova all'assistente in
modalità non interattiva. Se non risponde, avvia il flusso di autenticazione
browser/device della CLI: `claude auth login` per Claude Code, oppure
`codex login --device-auth` per Codex. Questo mostra un URL o apre il browser,
ma non lancia la UI interattiva dell'assistente. Dopo l'autenticazione lo script
riprova la domanda di prova; se ancora non riceve risposta, si ferma senza
prenotare nessun gruppo.

Se li hai installati entrambi, senza flag lo script prova prima Claude e poi
Codex. Se specifichi una CLI, usa solo quella: `--codex` non prova Claude, e
`--claude` non prova Codex. Puoi anche passare `0` per disabilitare
esplicitamente una CLI. Per esempio, per usare solo Codex:

```sh
uv run traduci.py --codex
```

### 4. uv

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
uv run traduci.py
```

`uv` scarica da solo le librerie che servono: non devi installare nulla a mano.

Il traduttore sceglie un gruppo per te e inizia a lavorare.
Un gruppo vero contiene circa mille voci e la traduzione richiede parecchie ore.

Puoi interromperla e riprenderla in qualunque momento.
Una volta completata, viene generata un contributo (una pull request).
Verrà fatta una verifica manuale e poi accettata.

Una volta completato un gruppo puoi rieseguire lo script per tradurne un altro.

Per fare una prova ci sono nove gruppi ridotti, da `test1` a `test9`, con una
voce per `test1` fino a nove per `test9`:

```sh
uv run traduci.py --group test1
```

Questi gruppi fanno una piccola traduzione e generano una pull request (che però verrà scartata).

Al primo avvio lo script ti guiderà attraverso le autenticazioni descritte
sopra. Poi lavorerà da solo:

1. crea il tuo fork del repository e lo clona in `~/.wikipedia-in-italiano`;
2. sceglie a caso un gruppo di voci ancora libero e lo prenota aprendo una issue;
3. per ogni voce: la scarica da Wikipedia, la converte in markdown e la fa
   tradurre subito dall'assistente AI;
4. carica il lavoro sul tuo fork ogni 10 voci tradotte;
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

Se Wikipedia risponde che hai superato il limite di richieste (`429 Too Many
Requests`), oppure Claude/Codex segnala che hai superato i limiti d'uso, lo
script si ferma subito e ti avvisa. Prima di uscire salva e pubblica sul fork
quello che era già stato prodotto; non apre la pull request e non chiude la issue
del gruppo. Rilanciando lo stesso comando più tardi, riprende dal branch e dalla
voce corretta.

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
