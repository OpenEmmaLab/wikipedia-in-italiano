"""Mappatura da titolo a percorso, e suddivisione ricorsiva in batch.

ALFABETO (37 simboli: a-z, 0-9, _)
==================================

Ogni carattere del titolo viene mappato cosi', nell'ordine:

1. minuscolizzato;
2. se e' a-z o 0-9 -> se' stesso;
3. altrimenti normalizzato in NFKD, prendendo la prima lettera/cifra ASCII
   che ne risulta (C-cediglia -> c, A-circonflesso -> a, n-tilde -> n);
4. se nulla di tutto cio' -> _

Carattere mancante (titolo piu' corto della profondita' richiesta) -> _

Il titolo e' preso verbatim dal dump, quindi con gli underscore al posto degli
spazi; l'underscore ricade nel caso 4 e mappa a se' stesso.

Perche' 37 e non 27: l'alfabeto precedente (a-z piu' _) collassava su _ le
cifre, la punteggiatura e ogni carattere non latino. Con la suddivisione
ricorsiva questo impedisce la terminazione: 1612 voci reali ('2035', 'Ç',
'東京') non contengono nessuna lettera ASCII, mapperebbero a _ a ogni
posizione e resterebbero per sempre in un unico gruppo sopra la soglia.

SUDDIVISIONE
============

Un gruppo con >= max_size voci viene suddiviso sul carattere successivo; con
meno di max_size diventa una foglia. Un list.txt esiste SOLO nelle foglie:
una cartella o contiene list.txt, o contiene sottocartelle, mai entrambi.
"""

import os
import string
import unicodedata

LETTERS = string.ascii_lowercase
DIGITS = string.digits
OTHER = "_"
BUCKET_CHARS = LETTERS + DIGITS + OTHER

# Soglia oltre la quale un gruppo viene ulteriormente suddiviso.
MAX_SIZE = 1000

_DIRECT = frozenset(LETTERS + DIGITS)

# La normalizzazione NFKD di un carattere e' costosa e i titoli ripetono
# moltissimo gli stessi caratteri: memorizzare l'esito e' un guadagno netto
# su decine di milioni di caratteri.
_map_cache = {}


def map_char(c):
    """Simbolo di bucket per un singolo carattere, secondo l'alfabeto a 37."""
    hit = _map_cache.get(c)
    if hit is not None:
        return hit

    lowered = c.lower()
    if lowered in _DIRECT:
        result = lowered
    else:
        result = OTHER
        # NFKD scompone le lettere accentate in lettera base + segno
        # diacritico: basta pescare il primo carattere ASCII utile.
        for ch in unicodedata.normalize("NFKD", lowered):
            if ch in _DIRECT:
                result = ch
                break

    _map_cache[c] = result
    return result


def bucket_char(title, index):
    """Simbolo di bucket per la posizione `index` di `title`."""
    if index >= len(title):
        return OTHER
    return map_char(title[index])


def bucket_prefix(title, depth):
    """I primi `depth` simboli di bucket di un titolo, come tupla."""
    return tuple(bucket_char(title, i) for i in range(depth))


def bucket_dir(root, prefix):
    """Cartella corrispondente a un prefisso di lunghezza variabile."""
    return os.path.join(root, *prefix)


def bucket_path(root, prefix):
    """Percorso del list.txt per un prefisso di lunghezza variabile."""
    return os.path.join(root, *prefix, "list.txt")


def split_recursive(entries, depth=0, prefix=(), max_size=MAX_SIZE):
    """Suddivide `entries` finche' ogni foglia scende sotto `max_size`.

    `entries` e' una sequenza di (page_id, title). Restituisce un dizionario
    {prefisso: [voci]} con le sole foglie.

    Un gruppo indivisibile diventa foglia ANCHE se supera max_size: e' il
    caso residuale delle voci senza alcun carattere mappabile ('東京', '!!!',
    'Æ'), circa 130 su 5,85 milioni. Senza questa uscita la ricorsione non
    terminerebbe.
    """
    if len(entries) < max_size:
        return {prefix: entries}

    # Un gruppo puo' condividere molti caratteri prima di divergere
    # ('List_of_a...' contro 'List_of_b...'): finche' un livello non separa
    # nulla si scende senza creare cartelle inutili, ma si continua a
    # cercare. Ci si ferma solo quando NESSUNA posizione separa piu' niente,
    # cioe' quando tutte le voci sono ormai identiche o esaurite: e' il caso
    # dei titoli non mappabili ('東京', '!!!'), che danno _ ovunque.
    longest = max(len(title) for _, title in entries)
    probe, extra = depth, ()
    while probe <= longest:
        groups = {}
        for entry in entries:
            groups.setdefault(bucket_char(entry[1], probe), []).append(entry)
        if len(groups) > 1:
            break
        extra += (next(iter(groups)),)
        probe += 1
    else:
        # Esaurite tutte le posizioni senza mai separare: le voci sono
        # indistinguibili sotto questo alfabeto (titoli non mappabili, o
        # identici). Foglia sopra soglia, accettata di proposito; il
        # prefisso NON viene allungato, perche' una catena di _ lunga
        # quanto il titolo non separerebbe comunque nulla.
        return {prefix: entries}

    prefix += extra
    depth = probe

    leaves = {}
    for symbol, group in groups.items():
        leaves.update(
            split_recursive(group, depth + 1, prefix + (symbol,), max_size)
        )
    return leaves
