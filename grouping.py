#!/usr/bin/env python3
"""Accorpa i batch troppo piccoli prodotti da create-wiki-batches.py.

IL PROBLEMA
===========

La suddivisione ricorsiva garantisce che nessun batch superi le 1000 voci,
ma non impone un minimo. Sui dati reali (5.846.491 voci in 71.004 batch) il
risultato e' molto sbilanciato verso il basso:

    1-99 righe      55.676 batch  (78%)
    100-499 righe   12.603 batch
    500-999 righe    2.725 batch

Media 82 righe, mediana 18: quattro batch su cinque contengono meno di 100
voci, e il costo di distribuirne e tracciarne uno supera il lavoro di
traduzione che contiene.

E' un effetto strutturale della ricorsione: un gruppo viene spaccato appena
supera la soglia, e i 37 figli si spartiscono le voci in modo disuguale. Un
gruppo da 1.100 voci puo' dare un figlio da 900 e trentasei da poche unita'.

COSA FA
=======

    ./grouping.py --batches batches --out groups

1. cancella <out> se esiste, per non accumulare run precedenti
2. enumera i list.txt di <batches> in ordine di percorso
3. li accorpa finche' il totale resta sotto soglia
4. scrive i gruppi in <out> e l'indice <out>/groups.txt

Legge soltanto da <batches>, che non viene mai modificato.

ORDINE
======

I batch si ordinano per percorso, lessicograficamente: lo stesso ordine di
`find batches -name list.txt | sort`. E' l'ordine naturale dell'albero, per
cui i file adiacenti condividono il prefisso piu' lungo possibile e
l'accorpamento unisce voci che si somigliano ('hotel_a' con 'hotel_b')
invece di accostare voci arbitrarie.

ACCUMULO
========

Un gruppo continua ad assorbire i batch successivi finche' il totale resta
sotto soglia, senza fermarsi alla prima coppia. La condizione e' '< 1000'
stretta, la stessa della suddivisione: un gruppo non deve mai raggiungere
la soglia che i batch rispettavano.

NOMI DEI FILE
=============

    <numero>-<prefisso>.txt

Il numero e' progressivo, il prefisso e' il percorso del PRIMO batch del
gruppo con gli '/' rimossi:

    groups/0001-0.txt
    groups/0003-10t.txt
    groups/4631-national_register_of_historic_places_listings_in_f.txt
    groups/7031-zy.txt

Il prefisso descrive la prima voce, non tutte: '0003-10t.txt' contiene anche
voci che iniziano diversamente. Chi consuma i gruppi deve leggere i titoli,
non dedurli dal nome.

groups.txt elenca i file di <out>, uno per riga, nell'ordine di scrittura:
serve a enumerare i gruppi senza scandire le sottocartelle.

GLI A-CAPO
==========

E' il punto in cui un accorpamento sbagliato corrompe i dati in silenzio.
Concatenare due file quando il primo non termina con '\\n' fonde l'ultima
riga del primo con la prima del secondo:

    12345\\tRome          <- manca il \\n finale
    67890\\tMilan
                          diventa
    12345\\tRome67890\\tMilan     <- una riga sola, due voci perse

La riga risultante contiene comunque un TAB, quindi supera un controllo di
formato superficiale: l'errore emerge solo contando le righe. Per questo il
'\\n' viene verificato e aggiunto se manca, invece di darlo per scontato.

RIPETIBILITA'
=============

Non serve alcuna ripresa: <out> viene cancellato e ricostruito da zero a
ogni run, e <batches> non viene mai toccato. Due run consecutivi danno un
risultato identico byte per byte.
"""

import argparse
import os
import shutil
import sys

from wikibatches import buckets

LIST_NAME = "list.txt"
INDEX_NAME = "groups.txt"

# Cartelle di servizio di create-wiki-batches.py: non contengono batch.
SKIP_DIRS = (".state", ".staging")


def log(message):
    print(message, file=sys.stderr, flush=True)


def fmt(n):
    """Numero con separatore delle migliaia, per leggerlo a colpo d'occhio."""
    return "{:,}".format(n).replace(",", ".")


def iter_batches(root):
    """I batch di `root`, in ordine di percorso.

    Restituisce coppie (percorso_relativo, numero_di_righe). L'ordine
    lessicografico e' quello che tiene vicini i prefissi simili, ed e' cio'
    che rende sensato accorpare batch adiacenti.
    """
    found = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        if LIST_NAME not in files:
            continue
        rel = os.path.relpath(dirpath, root)
        found.append(rel)

    found.sort()
    for rel in found:
        path = os.path.join(root, rel, LIST_NAME)
        with open(path, "rb") as fh:
            rows = sum(1 for _ in fh)
        yield rel, rows


def plan_groups(batches, max_size):
    """Raggruppa i batch adiacenti finche' restano sotto `max_size`.

    Restituisce una lista di (prefisso_del_primo, [percorsi], righe_totali).
    """
    groups = []
    current = None

    for rel, rows in batches:
        if current is None:
            current = [rel, [rel], rows]
            continue
        if current[2] + rows < max_size:
            current[1].append(rel)
            current[2] += rows
        else:
            groups.append(tuple(current))
            current = [rel, [rel], rows]

    if current is not None:
        groups.append(tuple(current))
    return groups


def group_name(index, prefix, width):
    """Nome del file: numero progressivo piu' prefisso senza separatori."""
    flat = prefix.replace(os.sep, "")
    return "%0*d-%s.txt" % (width, index, flat)


def write_group(out_root, name, sources, batches_root):
    """Concatena i batch di un gruppo in un solo file.

    Restituisce le righe scritte. Il '\\n' finale di ogni sorgente viene
    verificato e aggiunto se manca: senza, l'ultima riga di un file si
    salderebbe alla prima del successivo formando una riga sola che contiene
    due voci -- e che, avendo comunque un TAB, passerebbe inosservata.
    """
    rows = 0
    path = os.path.join(out_root, name)
    with open(path, "wb") as out:
        for rel in sources:
            src = os.path.join(batches_root, rel, LIST_NAME)
            with open(src, "rb") as fh:
                data = fh.read()
            if not data:
                continue
            rows += data.count(b"\n")
            if not data.endswith(b"\n"):
                # Sorgente senza terminatore: la riga finale e' comunque una
                # voce valida, va contata e chiusa prima di proseguire.
                rows += 1
                data += b"\n"
            out.write(data)
    return rows


def write_index(out_root, names):
    """L'elenco dei file di `out_root`, per enumerarli senza os.walk."""
    path = os.path.join(out_root, INDEX_NAME)
    with open(path, "w", encoding="utf-8") as fh:
        for name in names:
            fh.write("%s\n" % name)
    return path


def build(batches_root, out_root, max_size=buckets.MAX_SIZE):
    """Costruisce `out_root` da zero a partire da `batches_root`."""
    # Cancellare prima di ricominciare e' cio' che rende il comando sempre
    # sicuro da rilanciare: senza, un run precedente lascerebbe file che non
    # appartengono piu' a nessun gruppo.
    if os.path.isdir(out_root):
        log("Rimuovo %s da un run precedente" % out_root)
        shutil.rmtree(out_root)
    os.makedirs(out_root)

    log("[1/2] Leggo i batch da %s" % batches_root)
    batches = list(iter_batches(batches_root))
    if not batches:
        raise ValueError("nessun %s trovato in %s" % (LIST_NAME, batches_root))
    total_rows = sum(rows for _, rows in batches)
    log("      %s batch, %s voci" % (fmt(len(batches)), fmt(total_rows)))

    groups = plan_groups(batches, max_size)
    width = len(str(len(groups)))
    log("[2/2] Scrivo %s gruppi da meno di %s voci in %s"
        % (fmt(len(groups)), fmt(max_size), out_root))

    names, written = [], 0
    for n, (prefix, sources, _) in enumerate(groups, start=1):
        name = group_name(n, prefix, width)
        written += write_group(out_root, name, sources, batches_root)
        names.append(name)

    index = write_index(out_root, names)

    if written != total_rows:
        # Conservazione: se i conti non tornano il risultato non e' usabile,
        # e va detto subito invece di lasciarlo scoprire a valle.
        raise ValueError(
            "righe perse: %s in ingresso, %s in uscita"
            % (fmt(total_rows), fmt(written))
        )

    log("      indice in %s" % index)
    log("Fatto: %s voci in %s gruppi (da %s batch)"
        % (fmt(written), fmt(len(groups)), fmt(len(batches))))
    return len(groups)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--batches",
        default="batches",
        help="albero dei batch di partenza (default: %(default)s)",
    )
    parser.add_argument(
        "--out",
        default="groups",
        help="albero di destinazione, cancellato all'avvio "
        "(default: %(default)s)",
    )
    parser.add_argument(
        "--max-size",
        type=int,
        default=buckets.MAX_SIZE,
        metavar="N",
        help="accorpa finche' ogni gruppo ha meno di N voci "
        "(default: %(default)s)",
    )
    args = parser.parse_args(argv)

    if args.max_size < 1:
        parser.error("--max-size deve essere almeno 1")
    if not os.path.isdir(args.batches):
        parser.error(
            "cartella dei batch non trovata: %s\n"
            "Generala prima con ./create-wiki-batches.py" % args.batches
        )

    try:
        build(args.batches, args.out, max_size=args.max_size)
    except ValueError as exc:
        log("ERRORE: %s" % exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
