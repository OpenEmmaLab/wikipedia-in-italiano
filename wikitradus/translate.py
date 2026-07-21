"""Le due fasi del lavoro: estrazione delle voci e traduzione."""
import re
import time
import urllib.parse

from . import repo
from .cli import UsageLimitError
from .extract import NotFound, RateLimited, fetch_html, to_markdown

# Pausa fra le richieste a Wikipedia, per non martellare i loro server.
FETCH_PAUSE = 0.2
COMMIT_EVERY = 10

TRANSLATE_PROMPT = """\
Traduci in italiano il testo markdown qui sotto.

Usa un italiano idiomatico e naturale, come lo scriverebbe un madrelingua, non
una traduzione letterale. Conserva la struttura markdown (intestazioni, elenchi,
grassetti). Lascia in inglese i nomi propri che non hanno un esonimo italiano
consolidato. Non aggiungere link: il testo non ne contiene.

Rispondi con la sola traduzione: nessun commento, nota o preambolo, e nessun
blocco di codice attorno al risultato.

--- TESTO DA TRADURRE ---
{text}
"""

# La CLI può incorniciare la risposta in un blocco di codice nonostante la
# richiesta contraria: lo si toglie prima di salvare.
FENCE = re.compile(r"^```(?:markdown|md)?\n(.*)\n```$", re.DOTALL)


class LimitReached(Exception):
    """Il lavoro deve fermarsi perché un servizio ha segnalato limiti superati."""


def read_group(path):
    """Legge un file di gruppo: restituisce [(page_id, titolo), …]."""
    entries = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        page_id, _, title = line.partition("\t")
        entries.append((page_id.strip(), title.strip()))
    return entries


def _wiki_url(title, lang="en"):
    quoted = urllib.parse.quote(title.replace(" ", "_"), safe="")
    return f"https://{lang}.wikipedia.org/wiki/{quoted}"


def _extract_one(destination, page_id, title, lang):
    """Scarica una voce e la salva in markdown. None se non esiste più."""
    path = destination / f"{page_id}.md"
    if path.exists():
        return path
    try:
        markdown = to_markdown(fetch_html(title, lang), lang)
    except NotFound:
        # La voce è stata cancellata o rinominata dopo la generazione dei
        # batch: in entrambi i casi il titolo non risolve più e si salta.
        return None
    except RateLimited as exc:
        raise LimitReached(
            "Wikipedia ha risposto '429 Too Many Requests'. "
            "Ferma il lavoro e rilancialo più tardi."
        ) from exc
    except Exception as exc:
        print(f"  {title}: {exc}", flush=True)
        return None

    header = (
        f"# {title}\n\n"
        f"*[Voce originale su Wikipedia]({_wiki_url(title, lang)})*\n\n"
    )
    path.write_text(header + markdown + "\n")
    return path


def _translate_one(path, assistant, workdir):
    """Traduce un file sul posto. False se la CLI non ha prodotto nulla."""
    before = path.read_text()
    try:
        answer = assistant.ask(
            TRANSLATE_PROMPT.format(text=before), cwd=workdir.path
        )
    except UsageLimitError as exc:
        raise LimitReached(
            f"'{assistant.name}' segnala che sono stati superati i limiti "
            "d'uso. Rilancia lo script quando il limite si azzera."
        ) from exc
    except Exception as exc:
        print(f"  {path.name}: {exc}", flush=True)
        return False

    fenced = FENCE.match(answer.strip())
    result = (fenced.group(1) if fenced else answer).strip()

    # Se la risposta è vuota o identica all'originale la CLI non ha lavorato:
    # la voce non conta come tradotta e verrà ripresa al rilancio.
    if not result or result == before.strip():
        print(f"  {path.name}: invariato", flush=True)
        return False

    path.write_text(result + "\n")
    return True


def process_group(workdir, group, entries, assistant, lang="en"):
    """Estrae e traduce le voci una a una, alternando i due passi.

    Scaricare tutto in blocco significa mandare a Wikipedia centinaia di
    richieste ravvicinate, che finiscono per incontrare il rate limit
    (`429 Too Many Requests`). Traducendo subito ogni voce appena scaricata, le
    richieste si distanziano da sole: fra l'una e l'altra passano le decine di
    secondi che la CLI impiega a tradurre.
    """
    destination = workdir.group_dir(group)
    destination.mkdir(parents=True, exist_ok=True)
    done = workdir.translated_ids(group)

    pending = [(pid, title) for pid, title in entries if pid not in done]
    if not pending:
        print(f"Le {len(entries)} voci del gruppo sono già tradotte.")
        return 0

    print(
        f"Elaboro {len(pending)} voci con '{assistant.name}': "
        f"ognuna viene scaricata e subito tradotta.",
        flush=True,
    )
    translated = skipped = 0
    for index, (page_id, title) in enumerate(pending, 1):
        progress = f"[{index}/{len(pending)}]"

        try:
            path = _extract_one(destination, page_id, title, lang)
        except LimitReached:
            if workdir.commit_all(f"traduzioni: {group}, stop per limiti"):
                workdir.push()
            raise
        if path is None:
            skipped += 1
            print(f"  {progress} {title}: non disponibile", flush=True)
            continue

        try:
            translated_one = _translate_one(path, assistant, workdir)
        except LimitReached:
            if workdir.commit_all(f"traduzioni: {group}, stop per limiti"):
                workdir.push()
            raise

        if not translated_one:
            # L'originale resta su disco: al rilancio si riparte da lì senza
            # riscaricarlo.
            continue

        workdir.mark_translated(group, page_id)
        translated += 1
        print(f"  {progress} {title} tradotta", flush=True)

        if translated % COMMIT_EVERY == 0:
            workdir.commit_all(f"traduzioni: {group}, {translated} voci")
            workdir.push()
            print(f"  … {translated} voci pubblicate sul fork", flush=True)

        time.sleep(FETCH_PAUSE)

    if workdir.commit_all(f"traduzioni: {group}, {translated} voci tradotte"):
        workdir.push()
    print(f"Tradotte {translated} voci, saltate {skipped}.")
    return translated
