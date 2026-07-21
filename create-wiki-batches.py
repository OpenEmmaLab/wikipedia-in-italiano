#!/usr/bin/env python3
"""Estrai dai dump di Wikipedia inglese le pagine prive di langlink italiano,
e salvale in batch suddivisi per i primi due caratteri del titolo.

SORGENTE DATI
=============

Dump di en.wikipedia (non l'API MediaWiki):

- enwiki-latest-page.sql.gz      -> id e titolo di tutte le pagine
- enwiki-latest-langlinks.sql.gz -> langlink per pagina, filtrare ll_lang = 'it'

SELEZIONE
=========

Una pagina viene inclusa se soddisfa tutte queste condizioni:

- page_namespace = 0    -> solo voci vere e proprie, niente Talk:, User:, ecc.
- page_is_redirect = 0  -> esclude i redirect, che sono righe reali nel dump
                           ma non voci da tradurre
- non compare in langlinks con ll_lang = 'it'
                        -> non ha una versione corrispondente su it.wikipedia

Esempio di redirect da escludere: "Bradbury, Ray" (id 3468509) e' namespace 0
e privo di langlink it, ma rimanda solo a "Ray Bradbury".

OUTPUT
======

Albero a PROFONDITA' VARIABILE: si suddivide finche' ogni foglia contiene
meno di 1000 voci (--max-size).

    <c1>/<c2>/.../list.txt

Ogni livello usa un alfabeto di 37 simboli (a-z, 0-9, _). Un carattere del
titolo, preso verbatim dal dump, viene mappato cosi':

- minuscolizzato;
- se e' a-z o 0-9 -> se' stesso;
- altrimenti normalizzato in NFKD, prendendo la prima lettera/cifra ASCII
  (C-cediglia -> c, A-circonflesso -> a, n-tilde -> n);
- se nulla di tutto cio' -> _  (punteggiatura, CJK, e l'underscore stesso)
- carattere mancante -> _

Un list.txt esiste SOLO nelle foglie: una cartella o contiene list.txt, o
contiene sottocartelle, mai entrambi.

Esempi (a sinistra il page_title come appare nel dump), con la profondita'
che dipende da quante voci condividono il prefisso:

    Rome          -> r/o/m/list.txt
    1984          -> 1/9/list.txt
    R2-D2         -> r/2/list.txt
    Ray_Bradbury  -> r/a/y/list.txt
    A_Beautiful   -> a/_/b/list.txt
    Cesena        -> c/e/s/list.txt   <- 'Ç' finisce nello stesso ramo di 'c'

Un gruppo che nessuna posizione riesce piu' a separare (titoli identici, o
privi di caratteri mappabili come '東京', '!!!') diventa foglia ANCHE se
supera la soglia: sono ~130 voci su 5,85 milioni, e senza questa uscita la
ricorsione non terminerebbe.

FORMATO list.txt
================

Una riga per pagina, due campi separati da un singolo carattere TAB:

    <page_id>\\t<page_title>

- page_id    -> page.page_id del dump, intero decimale
- page_title -> page.page_title del dump, VERBATIM, quindi con gli underscore
                al posto degli spazi ("Fahrenheit_451", non "Fahrenheit 451")

Codifica UTF-8, terminatore di riga \\n.

Il titolo non puo' contenere TAB ne' newline: MediaWiki li vieta nei titoli,
quindi uno split sul primo TAB e' sempre corretto.

COME REPERIRE LA PAGINA
=======================

Entrambi i campi bastano da soli a raggiungere la pagina (verificato, HTTP 200):

    per id      https://en.wikipedia.org/?curid=<page_id>
    per titolo  https://en.wikipedia.org/wiki/<page_title>

Preferire l'id: e' stabile e continua a risolvere anche se la voce viene
rinominata dopo la generazione del dump.

Per interrogare l'API MediaWiki con il titolo servono gli spazi al posto
degli underscore, poi URL-encoded:

    page_title      Fahrenheit_451
    titles=         Fahrenheit 451     -> titles=Fahrenheit%20451

Per costruire l'URL /wiki/ invece il titolo va usato cosi' com'e', con gli
underscore.

USO
===

    ./create-wiki-batches.py --page-dump enwiki-latest-page.sql.gz \\
                             --langlinks-dump enwiki-latest-langlinks.sql.gz \\
                             --out batches

LE TRE FASI
===========

Per sapere se un gruppo va suddiviso bisogna conoscerne la dimensione, cioe'
aver gia' visto tutte le voci: non si puo' decidere il file di destinazione
guardando solo il titolo, come faceva la versione a due livelli. Quindi:

    [1/3]  estrae gli id con langlink italiano
    [2/3]  scansiona `page`, filtra, e scrive in <out>/.staging/<c>/list.txt
           (37 file, un solo livello)
    [3/3]  per ogni file di staging: lo carica in memoria, lo suddivide
           ricorsivamente, scrive le foglie definitive, poi lo rimuove

Il dataset intero (5,85M titoli) non entra comodamente in memoria, ma ogni
singolo bucket di staging si', ed e' l'unica cosa che serve alla volta.

INTERRUZIONE E RIPRESA
======================

Il lavoro dura ore, quindi si puo' interrompere (Ctrl-C, kill, crash) e
rilanciare lo STESSO comando: riprende da dove si era fermato.

Sotto <out>/.state/ vivono i file intermedi:

    it-ids.bin      gli id con langlink italiano, gia' filtrati e ordinati.
                    Estrarli richiede di attraversare 548 MB compressi, quindi
                    le riprese successive saltano del tutto la fase [1/3].
    it-ids.done     marcatore: senza, il .bin e' considerato incompleto
    progress.json   tuple gia' processate, righe scritte e dimensione di ogni
                    file di staging all'ultimo checkpoint (fase [2/3])
    stage3.json     quali bucket di staging sono gia' stati suddivisi

L'invariante che rende sicura la ripresa della fase [2/3]: si scrivono prima
i dati (flush + fsync), poi il checkpoint. Se il processo muore in mezzo si
rifa' un po' di lavoro, mai il contrario. Alla ripresa i file di staging
vengono riportati alla dimensione registrata nel checkpoint, scartando le
righe finite su disco dopo di esso: senza quel taglio verrebbero riscritte
in append e duplicate.

La fase [3/3] non ha bisogno di checkpoint per byte: suddividere un bucket
e' idempotente, da' sempre le stesse foglie. Basta sapere quali bucket sono
conclusi per saltarli, e riscrivere da zero quello interrotto.

    --restart           ignora lo stato e rifa' tutto da zero
    --checkpoint-every  ogni quante tuple salvare (default 1.000.000)
    --max-size          soglia di suddivisione (default 1000)
"""

import argparse
import array
import os
import shutil
import sys
import time

from wikibatches import buckets, state
from wikibatches.sqldump import iter_rows

# Indici di colonna, dallo schema dei dump enwiki.
# page: (page_id, page_namespace, page_title, page_is_redirect, ...)
PAGE_ID, PAGE_NAMESPACE, PAGE_TITLE, PAGE_IS_REDIRECT = 0, 1, 2, 3
# langlinks: (ll_from, ll_lang, ll_title)
LL_FROM, LL_LANG = 0, 1

MAIN_NAMESPACE = "0"
NOT_REDIRECT = "0"
TARGET_LANG = "it"

# Ogni quante tuple stampare una riga di avanzamento. I dump enwiki hanno
# decine di milioni di righe: un valore alto renderebbe lo script muto per
# minuti, uno basso inonderebbe il terminale.
PROGRESS_EVERY = 250_000

# Ogni quante tuple salvare un checkpoint. Piu' e' frequente, meno lavoro si
# rifa' dopo un'interruzione, ma ogni checkpoint costa un fsync.
CHECKPOINT_EVERY = 1_000_000


# Partizionamento grossolano della fase [2/3], rimosso a fine lavoro.
STAGING_DIR = ".staging"


def log(message):
    print(message, file=sys.stderr, flush=True)


def staging_path(root, symbol):
    return os.path.join(root, STAGING_DIR, symbol, "list.txt")


def fmt(n):
    """Numero con separatore delle migliaia, per leggerlo a colpo d'occhio."""
    return "{:,}".format(n).replace(",", ".")


def fmt_secs(seconds):
    seconds = int(seconds)
    if seconds < 60:
        return "%ds" % seconds
    if seconds < 3600:
        return "%dm%02ds" % (seconds // 60, seconds % 60)
    return "%dh%02dm" % (seconds // 3600, (seconds % 3600) // 60)


class Progress:
    """Righe di avanzamento con velocita' e tempo trascorso."""

    def __init__(self, total_hint=0):
        self.start = time.time()
        self.total_hint = total_hint

    def elapsed(self):
        return fmt_secs(time.time() - self.start)

    def _rate(self, done):
        delta = time.time() - self.start
        return done / delta if delta > 0 else 0.0

    def report(self, seen, written):
        rate = self._rate(max(seen - self.total_hint, 1))
        log("      %s tuple | %s selezionate | %s tuple/s | %s"
            % (fmt(seen), fmt(written), fmt(int(rate)), self.elapsed()))

    def skipping(self, seen, skip):
        pct = (seen * 100.0 / skip) if skip else 100.0
        log("      salto %s/%s tuple gia' fatte (%.0f%%)"
            % (fmt(seen), fmt(skip), pct))

    def checkpoint(self, seen):
        log("      checkpoint salvato a %s tuple" % fmt(seen))


def load_translated_ids(path, strict=True):
    """Insieme dei page_id che hanno gia' un langlink italiano.

    Gli id vengono raccolti in un array('l') e poi ordinati: per ~1.5M voci
    questo occupa ~12 MB contro i ~90 MB di un set di int Python, e la
    ricerca binaria successiva resta O(log n).

    Con `strict` un dump troncato interrompe l'esecuzione: langlinks
    incompleto significa dare per non tradotte pagine che invece lo sono,
    cioe' esattamente l'errore che questo script deve evitare.
    """
    ids = array.array("l")
    seen = 0
    progress = Progress()

    for row in iter_rows(path, "langlinks", strict=strict):
        seen += 1
        if seen % PROGRESS_EVERY == 0:
            log("      %s langlink letti | %s con versione it | %s"
                % (fmt(seen), fmt(len(ids)), progress.elapsed()))
        if len(row) > LL_LANG and row[LL_LANG] == TARGET_LANG:
            try:
                ids.append(int(row[LL_FROM]))
            except ValueError:
                continue

    log("      letti %s langlink in %s: %s pagine hanno la versione it"
        % (fmt(seen), progress.elapsed(), fmt(len(ids))))
    log("      ordino gli id per la ricerca binaria...")
    return array.array("l", sorted(ids))


def keep_row(row, translated):
    """Applica i tre filtri della spec a una tupla di `page`."""
    if len(row) <= PAGE_IS_REDIRECT:
        return False
    if row[PAGE_NAMESPACE] != MAIN_NAMESPACE:
        return False
    if row[PAGE_IS_REDIRECT] != NOT_REDIRECT:
        return False

    try:
        page_id = int(row[PAGE_ID])
    except ValueError:
        return False

    return not has_italian(translated, page_id)


def has_italian(sorted_ids, page_id):
    """Ricerca binaria su una lista ordinata di id."""
    lo, hi = 0, len(sorted_ids)
    while lo < hi:
        mid = (lo + hi) // 2
        value = sorted_ids[mid]
        if value == page_id:
            return True
        if value < page_id:
            lo = mid + 1
        else:
            hi = mid
    return False


class StagingWriter:
    """Scrive le righe nei 37 file di staging, uno per primo carattere.

    E' l'output della fase [2/3]: un partizionamento grossolano che serve
    solo a rendere il dataset affrontabile un pezzo alla volta nella fase
    [3/3]. Trentasette handle stanno largamente sotto il limite di file
    descriptor di macOS (256 di default), quindi restano tutti aperti.

    Con `resume` i file esistenti non vengono troncati: si prosegue in coda
    a quanto gia' scritto dal run interrotto.
    """

    def __init__(self, root, resume=False):
        self.root = root
        self.resume = resume
        self.handles = {}
        self.opened = set()

    def _handle(self, symbol):
        fh = self.handles.get(symbol)
        if fh is not None:
            return fh

        path = staging_path(self.root, symbol)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # Prima apertura: si tronca solo se non si sta riprendendo, per non
        # cancellare il lavoro di un run precedente.
        first_touch = symbol not in self.opened
        mode = "w" if (first_touch and not self.resume) else "a"
        fh = open(path, mode, encoding="utf-8")
        self.opened.add(symbol)
        self.handles[symbol] = fh
        return fh

    def write(self, title, page_id):
        self._handle(buckets.bucket_char(title, 0)).write(
            "%s\t%s\n" % (page_id, title)
        )

    def flush(self):
        """Forza su disco tutto il bufferizzato e rileva le dimensioni.

        Va chiamata prima di ogni checkpoint: se il processo muore dopo aver
        salvato il progresso ma prima che le righe siano scritte davvero, la
        ripresa saltera' pagine mai finite su disco.

        Restituisce {percorso_relativo: byte} per tutti i file toccati,
        cosi' il checkpoint sa a che punto erano.
        """
        for fh in self.handles.values():
            fh.flush()
            os.fsync(fh.fileno())

        sizes = {}
        for symbol in self.opened:
            path = staging_path(self.root, symbol)
            if os.path.exists(path):
                sizes[os.path.relpath(path, self.root)] = os.path.getsize(path)
        return sizes

    def close(self):
        for fh in self.handles.values():
            fh.flush()
            os.fsync(fh.fileno())
            fh.close()
        self.handles.clear()


def get_translated_ids(langlinks_dump, out_root, strict=True, resume=True):
    """Gli id con langlink italiano, riusando il file intermedio se c'e'.

    E' la fase piu' lenta (548 MB compressi da attraversare), quindi il
    risultato viene salvato: le riprese successive la saltano del tutto.
    """
    if resume:
        cached = state.load_ids(out_root)
        if cached is not None:
            log("[1/3] langlink italiani: riuso %s (%s id gia' estratti)"
                % (os.path.join(state.STATE_DIR, state.IDS_FILE), fmt(len(cached))))
            return cached

    log("[1/3] Estraggo i langlink italiani da %s" % langlinks_dump)
    log("      (fase lunga: il risultato viene salvato per le riprese)")
    ids = load_translated_ids(langlinks_dump, strict=strict)

    state.save_ids(out_root, ids)
    log("      salvati %s id in %s"
        % (fmt(len(ids)), os.path.join(state.STATE_DIR, state.IDS_FILE)))
    return ids


def stage(page_dump, translated, out_root, strict=True, resume=True,
          checkpoint_every=CHECKPOINT_EVERY):
    """Fase [2/3]: scansiona `page`, filtra, e scrive nei 37 file di staging.

    Restituisce il numero di righe scritte. Se `resume`, salta le tuple gia'
    processate da un run precedente.
    """
    skip, written, sizes = (
        state.load_progress(out_root) if resume else (0, 0, {})
    )
    if skip:
        log("[2/3] Riprendo da %s tuple gia' processate (%s righe gia' scritte)"
            % (fmt(skip), fmt(written)))
        # Scarta quanto e' finito su disco dopo l'ultimo checkpoint: quelle
        # righe verranno riscritte dalla ripresa e altrimenti sarebbero
        # duplicate.
        dropped = state.rollback_to_checkpoint(out_root, sizes)
        if dropped:
            log("      scartati %s byte scritti dopo l'ultimo checkpoint"
                % fmt(dropped))
    else:
        log("[2/3] Leggo le pagine da %s" % page_dump)

    writer = StagingWriter(out_root, resume=bool(skip))
    seen = 0
    progress = Progress(total_hint=skip)
    interrupted = False
    # Ultimo stato coerente noto: all'avvio e' il checkpoint da cui si
    # riprende, cosi' un'interruzione immediata non fa perdere terreno.
    safe = (skip, written, sizes)

    try:
        for row in iter_rows(page_dump, "page", strict=strict):
            seen += 1

            # Ripresa: le prime `skip` tuple sono gia' state scritte da un
            # run precedente, si saltano senza rielaborarle.
            if seen <= skip:
                if seen % PROGRESS_EVERY == 0:
                    progress.skipping(seen, skip)
                continue

            if seen % PROGRESS_EVERY == 0:
                progress.report(seen, written)

            if keep_row(row, translated):
                writer.write(row[PAGE_TITLE], int(row[PAGE_ID]))
                written += 1

            # Il checkpoint va DOPO aver processato la tupla, altrimenti
            # dichiarerebbe fatta una riga non ancora scritta e la ripresa
            # la salterebbe. E il flush va prima di leggere `written`, cosi'
            # il numero salvato descrive esattamente cio' che e' su disco:
            # se si muore qui si rifa' un po' di lavoro, mai il contrario.
            if seen % checkpoint_every == 0:
                # `safe` registra l'ultimo stato in cui tuple processate,
                # righe contate e byte su disco coincidono con certezza.
                safe = (seen, written, writer.flush())
                state.save_progress(out_root, *safe)
                progress.checkpoint(seen)
    except KeyboardInterrupt:
        interrupted = True
    finally:
        writer.close()
        if interrupted:
            # Si riparte dall'ultimo checkpoint coerente, non dalla posizione
            # corrente: l'interruzione puo' essere caduta a meta' di una riga,
            # e solo il checkpoint garantisce che byte e conteggi combacino.
            # Il rollback alla ripresa scarta l'eventuale coda parziale.
            state.save_progress(out_root, *safe)
            log("")
            log("Interrotto. Ultimo checkpoint: %s tuple, %s righe."
                % (fmt(safe[0]), fmt(safe[1])))
            log("Rilancia lo stesso comando per riprendere da qui.")
            raise KeyboardInterrupt

    # Arrivati in fondo: il progresso non serve piu' e la sua presenza
    # farebbe saltare tutto a un run successivo.
    state.clear_progress(out_root)
    log("      %s pagine lette, %s senza versione italiana in %s"
        % (fmt(seen), fmt(written), progress.elapsed()))
    return written


def read_staging(path):
    """Le voci (page_id, title) di un file di staging."""
    entries = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line:
                continue
            page_id, _, title = line.partition("\t")
            entries.append((page_id, title))
    return entries


def write_leaves(out_root, leaves):
    """Materializza le foglie, una cartella per prefisso.

    Le righe conservano l'ordine del dump: `split_recursive` non riordina
    nulla, cosi' due run sugli stessi dati danno file identici byte per byte.
    """
    rows = 0
    for prefix, entries in leaves.items():
        path = buckets.bucket_path(out_root, prefix)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            for page_id, title in entries:
                fh.write("%s\t%s\n" % (page_id, title))
            fh.flush()
            os.fsync(fh.fileno())
        rows += len(entries)
    return rows


def split_all(out_root, max_size=buckets.MAX_SIZE, resume=True):
    """Fase [3/3]: suddivide ogni bucket di staging in foglie definitive.

    Idempotente per bucket: rielaborarne uno da capo da' sempre le stesse
    foglie, quindi la ripresa si limita a saltare quelli gia' conclusi. Un
    bucket interrotto a meta' viene semplicemente rifatto: le foglie che
    aveva gia' scritto vengono sovrascritte con lo stesso contenuto.
    """
    done = state.load_split_done(out_root) if resume else set()
    if not resume:
        state.clear_split_done(out_root)

    staging_root = os.path.join(out_root, STAGING_DIR)
    if not os.path.isdir(staging_root):
        log("[3/3] nessuno staging da suddividere")
        return 0, 0

    symbols = sorted(
        s for s in os.listdir(staging_root)
        if os.path.exists(staging_path(out_root, s))
    )
    todo = [s for s in symbols if s not in done]

    log("[3/3] Suddivido %s bucket in foglie da meno di %s voci"
        % (fmt(len(todo)), fmt(max_size)))
    if done:
        log("      %s gia' fatti in un run precedente, saltati" % fmt(len(done)))

    progress = Progress()
    total_rows, total_leaves, oversize = 0, 0, []

    for symbol in todo:
        entries = read_staging(staging_path(out_root, symbol))
        # Il primo carattere e' gia' stato deciso dalla fase 2: la
        # suddivisione riparte da li', non da zero.
        leaves = buckets.split_recursive(
            entries, depth=1, prefix=(symbol,), max_size=max_size
        )
        total_rows += write_leaves(out_root, leaves)
        total_leaves += len(leaves)
        for prefix, group in leaves.items():
            if len(group) >= max_size:
                oversize.append(("/".join(prefix), len(group)))

        done.add(symbol)
        state.save_split_done(out_root, done)
        log("      %s: %s voci -> %s foglie | %s"
            % (symbol, fmt(len(entries)), fmt(len(leaves)), progress.elapsed()))

    if oversize:
        # Gruppi che nessuna posizione riesce piu' a separare: previsti dalla
        # spec, ma vanno detti, non nascosti.
        log("      %s foglie restano sopra soglia (voci indistinguibili):"
            % fmt(len(oversize)))
        for path, count in oversize:
            log("        %s -> %s voci" % (path or "<radice>", fmt(count)))

    return total_rows, total_leaves


def remove_staging(out_root):
    """Rimuove lo staging: a lavoro concluso e' solo spazio occupato."""
    staging_root = os.path.join(out_root, STAGING_DIR)
    if os.path.isdir(staging_root):
        shutil.rmtree(staging_root)


def build(page_dump, langlinks_dump, out_root, strict=True, resume=True,
          checkpoint_every=CHECKPOINT_EVERY, max_size=buckets.MAX_SIZE):
    """Genera i batch nelle tre fasi. Se `resume`, riprende da dove un run
    precedente si era interrotto."""
    state.ensure(out_root)

    if not resume:
        # Senza questa pulizia un progress.json rimasto da prima farebbe
        # saltare tuple in un run che dovrebbe rifare tutto.
        state.clear_progress(out_root)
        state.clear_split_done(out_root)
        remove_staging(out_root)

    translated = get_translated_ids(
        langlinks_dump, out_root, strict=strict, resume=resume
    )

    # Se la fase 3 era gia' iniziata, lo staging e' completo: la fase 2 non
    # ha piu' nulla da fare e rifarla ricostruirebbe file gia' consumati.
    if resume and state.load_split_done(out_root):
        log("[2/3] staging gia' completo, salto la scansione")
    else:
        stage(page_dump, translated, out_root, strict=strict, resume=resume,
              checkpoint_every=checkpoint_every)

    written, leaves = split_all(out_root, max_size=max_size, resume=resume)
    remove_staging(out_root)
    state.clear_split_done(out_root)

    log("Fatto: %s voci da tradurre in %s batch" % (fmt(written), fmt(leaves)))
    return written


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--page-dump",
        default="enwiki-latest-page.sql.gz",
        help="dump della tabella page (default: %(default)s)",
    )
    parser.add_argument(
        "--langlinks-dump",
        default="enwiki-latest-langlinks.sql.gz",
        help="dump della tabella langlinks (default: %(default)s)",
    )
    parser.add_argument(
        "--out",
        default="batches",
        help="cartella radice dell'output (default: %(default)s)",
    )
    parser.add_argument(
        "--allow-truncated",
        action="store_true",
        help="prosegui anche con un dump incompleto (default: interrompi, "
        "perche' un langlinks troncato produce falsi 'da tradurre')",
    )
    parser.add_argument(
        "--restart",
        action="store_true",
        help="ignora lo stato salvato e rifai tutto da zero "
        "(default: riprendi da dove ci si era interrotti)",
    )
    parser.add_argument(
        "--checkpoint-every",
        type=int,
        default=CHECKPOINT_EVERY,
        metavar="N",
        help="salva un checkpoint ogni N tuple (default: %(default)s)",
    )
    parser.add_argument(
        "--max-size",
        type=int,
        default=buckets.MAX_SIZE,
        metavar="N",
        help="suddividi finche' ogni batch ha meno di N voci "
        "(default: %(default)s)",
    )
    args = parser.parse_args(argv)

    if args.max_size < 1:
        parser.error("--max-size deve essere almeno 1")

    # Su una ripresa i dump possono non servire piu': gli id italiani sono
    # gia' in .state/, e a staging completo la scansione di `page` non viene
    # rifatta. Si pretende quindi solo cio' che verra' davvero letto.
    resuming = not args.restart
    needed = []
    if not (resuming and state.load_ids(args.out) is not None):
        needed.append(args.langlinks_dump)
    if not (resuming and state.load_split_done(args.out)):
        needed.append(args.page_dump)

    for path in needed:
        if not os.path.exists(path):
            parser.error(
                "dump non trovato: %s\n"
                "Scaricalo da https://dumps.wikimedia.org/enwiki/latest/" % path
            )

    try:
        build(
            args.page_dump,
            args.langlinks_dump,
            args.out,
            strict=not args.allow_truncated,
            resume=not args.restart,
            checkpoint_every=args.checkpoint_every,
            max_size=args.max_size,
        )
    except EOFError as exc:
        log("ERRORE: %s" % exc)
        log("Il dump e' incompleto: riscaricalo, oppure usa --allow-truncated")
        return 1
    except KeyboardInterrupt:
        # build() ha gia' salvato lo stato e spiegato come riprendere.
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
