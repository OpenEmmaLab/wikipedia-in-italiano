"""Le due fasi del lavoro: estrazione delle voci e traduzione."""
import re
import time
import urllib.parse

from . import repo
from .extract import NotFound, fetch_html, resolve_titles, to_markdown

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


def extract_group(workdir, group, entries, lang="en"):
    """Fase 1: estrae in markdown tutte le voci non ancora presenti.

    Le voci già su disco vengono saltate, così una ripresa non riscarica nulla.
    """
    destination = workdir.group_dir(group)
    destination.mkdir(parents=True, exist_ok=True)

    pending = [
        (page_id, title) for page_id, title in entries
        if not (destination / f"{page_id}.md").exists()
    ]
    if not pending:
        print(f"Le {len(entries)} voci del gruppo sono già estratte.")
        return 0

    print(f"Risolvo i titoli correnti di {len(pending)} voci…", flush=True)
    titles = resolve_titles([int(page_id) for page_id, _ in pending], lang)

    extracted = skipped = 0
    for index, (page_id, original_title) in enumerate(pending, 1):
        # Il titolo risolto segue le rinomine; se manca, la voce è cancellata.
        title = titles.get(int(page_id))
        if title is None:
            skipped += 1
            continue
        try:
            markdown = to_markdown(fetch_html(title, lang), lang)
        except NotFound:
            skipped += 1
            continue
        except Exception as exc:
            print(f"  errore su {title}: {exc}", flush=True)
            skipped += 1
            continue

        header = f"# {title}\n\n*[Voce originale su Wikipedia]({_wiki_url(title, lang)})*\n\n"
        (destination / f"{page_id}.md").write_text(header + markdown + "\n")
        extracted += 1
        if index % 50 == 0:
            print(f"  {index}/{len(pending)} — estratte {extracted}", flush=True)
        time.sleep(FETCH_PAUSE)

    print(f"Estratte {extracted} voci, saltate {skipped}.")
    return extracted


def translate_group(workdir, group, assistant, fork):
    """Fase 2: traduce le voci non ancora elencate in translated.txt."""
    destination = workdir.group_dir(group)
    done = workdir.translated_ids(group)
    pending = sorted(
        path for path in destination.glob("*.md") if path.stem not in done
    )
    if not pending:
        print("Tutte le voci estratte sono già tradotte.")
        return 0

    print(f"Traduco {len(pending)} voci con '{assistant.name}'…", flush=True)
    translated = 0
    for index, path in enumerate(pending, 1):
        before = path.read_text()
        try:
            answer = assistant.ask(
                TRANSLATE_PROMPT.format(text=before), cwd=workdir.path
            )
        except Exception as exc:
            print(f"  [{index}/{len(pending)}] {path.name}: {exc}", flush=True)
            continue

        fenced = FENCE.match(answer.strip())
        result = (fenced.group(1) if fenced else answer).strip()

        # Se la risposta è vuota o identica all'originale la CLI non ha
        # lavorato: la voce non conta come tradotta e verrà ripresa al rilancio.
        if not result or result == before.strip():
            print(f"  [{index}/{len(pending)}] {path.name}: invariato", flush=True)
            continue

        path.write_text(result + "\n")
        workdir.mark_translated(group, path.stem)
        translated += 1
        print(f"  [{index}/{len(pending)}] {path.name} tradotta", flush=True)

        if translated % COMMIT_EVERY == 0:
            workdir.commit_all(f"traduzioni: {group}, {translated} voci")
            workdir.push()
            print(f"  … {translated} voci pubblicate sul fork", flush=True)

    if workdir.commit_all(f"traduzioni: {group}, {translated} voci tradotte"):
        workdir.push()
    return translated
