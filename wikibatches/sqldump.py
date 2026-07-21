"""Parser per i dump SQL di MediaWiki.

I dump sono file .sql.gz contenenti istruzioni INSERT con molte tuple per riga:

    INSERT INTO `page` VALUES (1,0,'Rome',0,0,0.123,'2024...',...),(2,0,...);

Le righe sono enormi (fino a ~1 MB), quindi si legge a blocchi e si emettono
le tuple via generatore, senza mai materializzare l'intero dump in memoria.
"""

import codecs
import os
import warnings
import zlib

# 16 = attende un header gzip; 15 = finestra massima.
_GZIP_WBITS = 16 + zlib.MAX_WBITS


def _parse_tuples(text, start):
    """Estrae le tuple da `text` a partire da `start`.

    Restituisce (righe, indice_ripresa). L'indice di ripresa e' l'inizio
    dell'ultima tupla incompleta, cosi' il chiamante puo' concatenarla al
    blocco successivo senza perdere dati a cavallo dei confini.

    Il parsing e' carattere per carattere perche' i valori possono contenere
    virgole, parentesi e apici escapati: uno split ingenuo li spezzerebbe.
    """
    rows = []
    i = start
    n = len(text)
    resume = start

    while i < n:
        # Salta separatori fino all'inizio di una tupla.
        while i < n and text[i] != "(":
            if text[i] == ";":
                return rows, i
            i += 1
        if i >= n:
            break

        tuple_start = i
        i += 1
        fields = []
        buf = []
        in_string = False
        complete = False

        while i < n:
            c = text[i]

            if in_string:
                if c == "\\":
                    # Escape MySQL: il carattere seguente e' letterale.
                    if i + 1 >= n:
                        break
                    buf.append(_unescape(text[i + 1]))
                    i += 2
                    continue
                if c == "'":
                    in_string = False
                    i += 1
                    continue
                buf.append(c)
                i += 1
                continue

            if c == "'":
                in_string = True
                i += 1
                continue
            if c == ",":
                fields.append("".join(buf))
                buf = []
                i += 1
                continue
            if c == ")":
                fields.append("".join(buf))
                i += 1
                complete = True
                break

            buf.append(c)
            i += 1

        if not complete:
            # Tupla troncata dal confine del blocco: la si riprende dopo.
            resume = tuple_start
            break

        rows.append(fields)
        resume = i

    return rows, resume


_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "0": "\0", "b": "\b", "Z": "\x1a"}


def _unescape(c):
    return _ESCAPES.get(c, c)


def _iter_text(path, chunk_size, on_truncated):
    """Decomprime il dump a blocchi, tollerando uno stream gzip troncato.

    Non si usa gzip.open: su un file scaricato a meta' solleva EOFError
    perche' manca il trailer, e i dati gia' decompressi vanno persi.
    zlib.decompressobj invece restituisce tutto cio' che e' decodificabile
    fino al punto di troncamento.
    """
    decomp = zlib.decompressobj(_GZIP_WBITS)
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

    with open(path, "rb") as fh:
        while True:
            raw = fh.read(chunk_size)
            if not raw:
                break
            try:
                data = decomp.decompress(raw)
            except zlib.error as exc:
                on_truncated(exc)
                break
            if data:
                yield decoder.decode(data)

            if decomp.eof:
                # Fine dello stream gzip: i dump reali sono un solo membro,
                # eventuali byte successivi non interessano.
                break

    tail = decoder.decode(b"", final=True)
    if tail:
        yield tail

    if not decomp.eof:
        on_truncated(EOFError("stream gzip incompleto"))


def iter_rows(path, table, chunk_size=4 << 20, strict=False):
    """Itera le tuple della tabella `table` nel dump gzip in `path`.

    Ogni tupla e' una lista di stringhe, nell'ordine delle colonne del dump.

    Se `strict` e' True un dump troncato solleva EOFError invece di essere
    letto parzialmente: da usare quando i conteggi devono essere completi.
    """
    truncated = []

    def on_truncated(exc):
        if strict:
            raise exc
        truncated.append(exc)

    marker = "INSERT INTO `%s` VALUES " % table
    # Un INSERT si estende su piu' blocchi e il marker compare una volta sola:
    # serve ricordare se si sta gia' leggendo tuple.
    inside = False
    pending = ""

    for chunk in _iter_text(path, chunk_size, on_truncated):
        text = pending + chunk

        while True:
            if not inside:
                pos = text.find(marker)
                if pos < 0:
                    # Nessun marker: tienine in sospeso una coda lunga
                    # quanto basta a ricomporne uno spezzato a meta'.
                    keep = len(marker)
                    pending = text[-keep:] if len(text) > keep else text
                    break
                text = text[pos + len(marker):]
                inside = True

            rows, resume = _parse_tuples(text, 0)
            for row in rows:
                yield row

            if resume < len(text) and text[resume] == ";":
                # Fine dell'INSERT: torna a cercare il marker successivo.
                text = text[resume + 1:]
                inside = False
                continue

            pending = text[resume:]
            break

    # Coda finale: puo' contenere un'ultima tupla completa.
    if pending:
        if inside:
            rows, _ = _parse_tuples(pending, 0)
            for row in rows:
                yield row
        else:
            pos = pending.find(marker)
            if pos >= 0:
                rows, _ = _parse_tuples(pending[pos + len(marker):], 0)
                for row in rows:
                    yield row

    if truncated:
        # Un dump incompleto produrrebbe una lista che sembra buona ma non lo
        # e': meglio dirlo forte invece di restituire dati parziali in
        # silenzio.
        warnings.warn(
            "dump troncato (%s): %s -- i risultati sono incompleti"
            % (os.path.basename(path), truncated[0]),
            RuntimeWarning,
            stacklevel=2,
        )
