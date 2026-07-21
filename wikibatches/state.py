"""Stato su disco per rendere lo script interrompibile e ripartibile.

Sotto la radice di output vive una cartella .state/ con:

    it-ids.bin      gli id con langlink italiano, gia' filtrati e ordinati
                    (array binario) -- evita di rileggere i 548 MB di
                    langlinks a ogni ripresa
    it-ids.done     scritto solo a fase conclusa: senza questo file il .bin
                    e' considerato incompleto e viene rigenerato
    progress.json   quante tuple di `page` sono gia' state processate e
                    quante righe scritte, per riprendere dal punto giusto
                    (fase 2, scrittura dello staging)
    stage3.json     quali bucket di staging sono gia' stati suddivisi in
                    foglie definitive (fase 3)

Il criterio di ripresa della fase 2 e' l'indice di tupla nel dump: i dump
sono file statici e il parser li attraversa sempre nello stesso ordine,
quindi la n-esima tupla e' sempre la stessa. Saltare le prime N tuple e'
molto piu' veloce che riscriverle, perche' evita il lavoro di selezione e
I/O.

La fase 3 invece e' idempotente per bucket: rielaborarne uno da capo da'
sempre lo stesso risultato, quindi basta segnare quali sono conclusi.
"""

import array
import json
import os

STATE_DIR = ".state"
IDS_FILE = "it-ids.bin"
IDS_DONE = "it-ids.done"
PROGRESS_FILE = "progress.json"
SPLIT_FILE = "stage3.json"

# 'l' e' lo stesso typecode usato per costruire l'array in memoria.
IDS_TYPECODE = "l"


def state_dir(out_root):
    return os.path.join(out_root, STATE_DIR)


def ensure(out_root):
    path = state_dir(out_root)
    os.makedirs(path, exist_ok=True)
    return path


def _p(out_root, name):
    return os.path.join(state_dir(out_root), name)


def load_ids(out_root):
    """Gli id italiani salvati da un run precedente, o None se assenti.

    Restituisce None anche se manca il marcatore .done: un .bin scritto a
    meta' darebbe un filtro parziale, cioe' pagine dichiarate da tradurre
    che invece sono gia' tradotte.
    """
    ids_path = _p(out_root, IDS_FILE)
    if not os.path.exists(ids_path) or not os.path.exists(_p(out_root, IDS_DONE)):
        return None

    ids = array.array(IDS_TYPECODE)
    size = os.path.getsize(ids_path)
    if size % ids.itemsize:
        return None  # file corrotto: meglio rifare la fase
    with open(ids_path, "rb") as fh:
        ids.fromfile(fh, size // ids.itemsize)
    return ids


def save_ids(out_root, ids):
    """Salva gli id e poi il marcatore, in quest'ordine.

    Scrivere prima i dati e solo dopo il .done fa si' che un'interruzione
    nel mezzo lasci uno stato riconoscibile come incompleto.
    """
    ensure(out_root)
    tmp = _p(out_root, IDS_FILE + ".tmp")
    with open(tmp, "wb") as fh:
        ids.tofile(fh)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, _p(out_root, IDS_FILE))

    with open(_p(out_root, IDS_DONE), "w") as fh:
        fh.write("%d\n" % len(ids))
        fh.flush()
        os.fsync(fh.fileno())


def load_progress(out_root):
    """(tuple_processate, righe_scritte, dimensioni_file) del run precedente.

    Restituisce (0, 0, {}) se non c'e' nulla di riusabile.
    """
    path = _p(out_root, PROGRESS_FILE)
    if not os.path.exists(path):
        return 0, 0, {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return (
            int(data.get("pages_seen", 0)),
            int(data.get("rows_written", 0)),
            data.get("sizes") or {},
        )
    except (ValueError, OSError):
        # Checkpoint illeggibile (es. interrotto durante la scrittura):
        # si riparte dall'inizio invece di fidarsi di un numero sbagliato.
        return 0, 0, {}


def save_progress(out_root, pages_seen, rows_written, sizes=None):
    """Checkpoint atomico: scrittura su file temporaneo e rename.

    `sizes` mappa il percorso relativo di ogni list.txt toccato alla sua
    dimensione in byte al momento del flush, cosi' la ripresa puo' scartare
    cio' che e' finito su disco dopo questo checkpoint.
    """
    ensure(out_root)
    tmp = _p(out_root, PROGRESS_FILE + ".tmp")
    payload = {
        "pages_seen": pages_seen,
        "rows_written": rows_written,
        "sizes": sizes or {},
    }
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, _p(out_root, PROGRESS_FILE))


def rollback_to_checkpoint(out_root, sizes):
    """Riporta ogni list.txt alla dimensione registrata nel checkpoint.

    Tra l'ultimo checkpoint e l'interruzione il writer puo' aver gia'
    scaricato su disco righe non contabilizzate. Senza questo taglio la
    ripresa le riscriverebbe in append, duplicandole.

    Si lavora in byte, non in righe: la posizione registrata al momento del
    flush e' l'unico punto di cui si sa con certezza che corrisponde al
    conteggio salvato. Restituisce i byte scartati.
    """
    dropped = 0
    for rel_path, size in sizes.items():
        path = os.path.join(out_root, rel_path)
        if not os.path.exists(path):
            continue
        actual = os.path.getsize(path)
        if actual > size:
            with open(path, "r+b") as fh:
                fh.truncate(size)
                fh.flush()
                os.fsync(fh.fileno())
            dropped += actual - size
    return dropped


def clear_progress(out_root):
    for name in (PROGRESS_FILE, PROGRESS_FILE + ".tmp"):
        try:
            os.unlink(_p(out_root, name))
        except OSError:
            pass


def load_split_done(out_root):
    """I bucket di staging gia' suddivisi dalla fase 3.

    La fase 3 e' idempotente per bucket: suddividerne uno produce sempre le
    stesse foglie. Non serve quindi un checkpoint per byte come nella fase
    2, basta sapere quali sono conclusi per saltarli alla ripresa.
    """
    path = _p(out_root, SPLIT_FILE)
    if not os.path.exists(path):
        return set()
    try:
        with open(path, encoding="utf-8") as fh:
            return set(json.load(fh).get("done", []))
    except (ValueError, OSError, AttributeError):
        return set()


def save_split_done(out_root, done):
    """Registra i bucket conclusi, con scrittura atomica."""
    ensure(out_root)
    tmp = _p(out_root, SPLIT_FILE + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"done": sorted(done)}, fh)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, _p(out_root, SPLIT_FILE))


def clear_split_done(out_root):
    for name in (SPLIT_FILE, SPLIT_FILE + ".tmp"):
        try:
            os.unlink(_p(out_root, name))
        except OSError:
            pass
