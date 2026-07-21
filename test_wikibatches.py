#!/usr/bin/env python3
"""Test per create-wiki-batches.py e grouping.py.
Eseguire con: python3 -m unittest -v"""

import gzip
import importlib.util
import os
import shutil
import tempfile
import unittest
import warnings

import grouping
from wikibatches import buckets, state
from wikibatches.sqldump import iter_rows

# Lo script ha un trattino nel nome, quindi non e' importabile direttamente.
_spec = importlib.util.spec_from_file_location(
    "create_wiki_batches",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "create-wiki-batches.py"),
)
cwb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cwb)


class TestBuckets(unittest.TestCase):
    def test_esempi_della_spec(self):
        casi = {
            "Rome": ("r", "o"),
            "rome": ("r", "o"),
            "1984": ("1", "9"),      # le cifre sono bucket propri
            "R": ("r", "_"),          # carattere mancante -> _
            "R2-D2": ("r", "2"),
            "Ray_Bradbury": ("r", "a"),
            "A_Beautiful": ("a", "_"),  # underscore = spazio -> _
            "Elsa": ("e", "l"),
        }
        for titolo, atteso in casi.items():
            self.assertEqual(buckets.bucket_prefix(titolo, 2), atteso, titolo)

    def test_titolo_vuoto(self):
        self.assertEqual(buckets.bucket_prefix("", 2), ("_", "_"))

    def test_alfabeto_37_simboli(self):
        self.assertEqual(len(buckets.BUCKET_CHARS), 37)
        self.assertEqual(len(set(buckets.BUCKET_CHARS)), 37)

    def test_accentate_ripiegano_sulla_lettera_base(self):
        # NFKD: le latine accentate finiscono nel ramo della lettera base,
        # invece di collassare tutte insieme in "altro".
        self.assertEqual(buckets.bucket_char("Çesena", 0), "c")
        self.assertEqual(buckets.bucket_char("Âme", 0), "a")
        self.assertEqual(buckets.bucket_char("ñandu", 0), "n")

    def test_non_mappabili_vanno_in_underscore(self):
        # Cio' che NFKD non riporta ad ASCII resta in "altro".
        self.assertEqual(buckets.bucket_char("東京", 0), "_")
        self.assertEqual(buckets.bucket_char("!!!", 0), "_")
        self.assertEqual(buckets.bucket_char("Ø", 0), "_")


class TestSuddivisioneRicorsiva(unittest.TestCase):
    def _voci(self, titoli):
        return [(i, t) for i, t in enumerate(titoli)]

    def _conserva(self, entries, foglie):
        """Nessuna voce persa, nessuna duplicata."""
        dentro = [e for gruppo in foglie.values() for e in gruppo]
        self.assertEqual(sorted(dentro), sorted(entries))

    def test_sotto_soglia_resta_una_foglia(self):
        voci = self._voci(["Rome"] * 10)
        foglie = buckets.split_recursive(voci, max_size=1000)
        self.assertEqual(list(foglie), [()])

    def test_sopra_soglia_si_suddivide(self):
        voci = self._voci(["Voce_%04d" % i for i in range(1500)])
        foglie = buckets.split_recursive(voci, max_size=100)
        self.assertGreater(len(foglie), 1)
        for gruppo in foglie.values():
            self.assertLess(len(gruppo), 100)
        self._conserva(voci, foglie)

    def test_prefisso_comune_lungo_poi_divergenza(self):
        # Regressione: fermarsi al primo livello che non separa lascerebbe
        # un'unica foglia enorme, perche' 'List_of_' e' comune a tutte.
        voci = self._voci(
            ["List_of_%s_things" % chr(97 + i % 26) for i in range(1500)]
        )
        foglie = buckets.split_recursive(voci, max_size=1000)
        self.assertEqual(len(foglie), 26)
        for gruppo in foglie.values():
            self.assertLess(len(gruppo), 1000)
        self._conserva(voci, foglie)

    def test_voci_indistinguibili_non_ciclano(self):
        # Titoli senza alcun carattere mappabile: nessuna posizione li
        # separa mai. Devono dare UNA foglia sopra soglia, non ricorsione
        # infinita.
        voci = self._voci(["東京京東"] * 1500)
        foglie = buckets.split_recursive(voci, max_size=1000)
        self.assertEqual(len(foglie), 1)
        self.assertEqual(len(next(iter(foglie.values()))), 1500)

    def test_titoli_identici_non_ciclano(self):
        voci = self._voci(["Stesso_titolo"] * 1200)
        foglie = buckets.split_recursive(voci, max_size=1000)
        self.assertEqual(len(foglie), 1)

    def test_ordine_del_dump_conservato(self):
        # Due run devono dare file identici byte per byte: la suddivisione
        # non deve riordinare nulla.
        voci = self._voci(["Voce_%04d" % i for i in range(1500)])
        foglie = buckets.split_recursive(voci, max_size=100)
        for gruppo in foglie.values():
            self.assertEqual(gruppo, sorted(gruppo, key=lambda e: e[0]))


class TestSqlDump(unittest.TestCase):
    def _dump(self, sql):
        fd, path = tempfile.mkstemp(suffix=".sql.gz")
        os.close(fd)
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            fh.write(sql)
        return path

    def test_parse_semplice(self):
        path = self._dump(
            "INSERT INTO `page` VALUES (1,0,'Rome',0),(2,0,'Milan',1);\n"
        )
        try:
            righe = list(iter_rows(path, "page"))
            self.assertEqual(righe[0][:4], ["1", "0", "Rome", "0"])
            self.assertEqual(righe[1][:4], ["2", "0", "Milan", "1"])
        finally:
            os.unlink(path)

    def test_apici_e_virgole_nel_titolo(self):
        # Una virgola dentro una stringa non deve spezzare la tupla,
        # e l'apice escapato deve restare nel titolo.
        path = self._dump(
            "INSERT INTO `page` VALUES (1,0,'Rome,_Italy',0),"
            "(2,0,'O\\'Brien',0);\n"
        )
        try:
            righe = list(iter_rows(path, "page"))
            self.assertEqual(righe[0][2], "Rome,_Italy")
            self.assertEqual(righe[1][2], "O'Brien")
        finally:
            os.unlink(path)

    def test_parentesi_nel_titolo(self):
        path = self._dump(
            "INSERT INTO `page` VALUES (1,0,'Mercury_(planet)',0);\n"
        )
        try:
            righe = list(iter_rows(path, "page"))
            self.assertEqual(righe[0][2], "Mercury_(planet)")
        finally:
            os.unlink(path)

    def test_tupla_a_cavallo_di_due_blocchi(self):
        # Con chunk_size minuscolo le tuple vengono spezzate a meta':
        # il parser deve ricomporle senza perderne nessuna.
        tuple_sql = ",".join(
            "(%d,0,'Page_%d',0)" % (i, i) for i in range(200)
        )
        path = self._dump("INSERT INTO `page` VALUES %s;\n" % tuple_sql)
        try:
            righe = list(iter_rows(path, "page", chunk_size=64))
            self.assertEqual(len(righe), 200)
            self.assertEqual(righe[0][2], "Page_0")
            self.assertEqual(righe[199][2], "Page_199")
        finally:
            os.unlink(path)

    def test_piu_insert_consecutivi(self):
        path = self._dump(
            "INSERT INTO `page` VALUES (1,0,'Uno',0);\n"
            "INSERT INTO `page` VALUES (2,0,'Due',0);\n"
        )
        try:
            righe = list(iter_rows(path, "page"))
            self.assertEqual([r[2] for r in righe], ["Uno", "Due"])
        finally:
            os.unlink(path)

    def test_dump_troncato_restituisce_cio_che_puo(self):
        # Un download interrotto fa sollevare EOFError a gzip: le tuple
        # gia' leggibili non devono andare perse (regressione: prima si
        # perdeva l'intero file).
        fd, path = tempfile.mkstemp(suffix=".sql.gz")
        os.close(fd)
        tuple_sql = ",".join("(%d,0,'P_%d',0)" % (i, i) for i in range(500))
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            fh.write("INSERT INTO `page` VALUES %s;\n" % tuple_sql)
        with open(path, "rb") as fh:
            blob = fh.read()
        with open(path, "wb") as fh:
            fh.write(blob[: int(len(blob) * 0.7)])  # tronca il gzip

        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                righe = list(iter_rows(path, "page"))
            self.assertGreater(len(righe), 0, "tutte le tuple perse")
            self.assertTrue(
                any(w.category is RuntimeWarning for w in caught),
                "il troncamento deve essere segnalato",
            )
            # strict=True invece deve fallire rumorosamente.
            with self.assertRaises(EOFError):
                list(iter_rows(path, "page", strict=True))
        finally:
            os.unlink(path)

    def test_ignora_altre_tabelle(self):
        path = self._dump(
            "INSERT INTO `revision` VALUES (9,9,'x',9);\n"
        )
        try:
            self.assertEqual(list(iter_rows(path, "page")), [])
        finally:
            os.unlink(path)


class TestSelezione(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.files = []

    def tearDown(self):
        shutil.rmtree(self.root)
        for path in self.files:
            if os.path.exists(path):
                os.unlink(path)

    def _dump(self, sql):
        fd, path = tempfile.mkstemp(suffix=".sql.gz")
        os.close(fd)
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            fh.write(sql)
        self.files.append(path)
        return path

    def _leggi(self, *prefix):
        path = buckets.bucket_path(self.root, prefix)
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as fh:
            return [r for r in fh.read().splitlines() if r]

    def _tutte(self):
        """Tutte le righe dell'albero, ovunque siano finite le foglie."""
        righe = []
        for dirpath, _, files in os.walk(self.root):
            if "list.txt" not in files:
                continue
            with open(os.path.join(dirpath, "list.txt"), encoding="utf-8") as fh:
                righe.extend(r for r in fh.read().splitlines() if r)
        return sorted(righe)

    def test_filtri_della_spec(self):
        page = self._dump(
            "INSERT INTO `page` VALUES "
            # tenuta: ns 0, non redirect, senza langlink it
            "(10,0,'Elsa',0),"
            # scartata: ha un langlink it
            "(11,0,'Rome',0),"
            # scartata: e' un redirect (caso "Bradbury,_Ray" della spec)
            "(3468509,0,'Bradbury,_Ray',1),"
            # scartata: namespace diverso da 0
            "(13,1,'Talk_page',0),"
            # tenuta
            "(14,0,'1984',0);\n"
        )
        langlinks = self._dump(
            "INSERT INTO `langlinks` VALUES "
            "(11,'it','Roma'),"
            "(10,'fr','Elsa'),"   # lingua diversa: non conta
            "(99,'it','Altro');\n"
        )

        scritte = cwb.build(page, langlinks, self.root)

        self.assertEqual(scritte, 2)
        # Poche voci: restano tutte insieme, ma solo quelle selezionate.
        self.assertEqual(self._tutte(), ["10\tElsa", "14\t1984"])

    def test_formato_riga(self):
        page = self._dump("INSERT INTO `page` VALUES (10951,0,'Fahrenheit_451',0);\n")
        langlinks = self._dump("INSERT INTO `langlinks` VALUES (1,'de','X');\n")

        cwb.build(page, langlinks, self.root)

        righe = self._tutte()
        self.assertEqual(righe, ["10951\tFahrenheit_451"])
        # Split sul primo TAB: due campi, titolo verbatim con underscore.
        id_, titolo = righe[0].split("\t", 1)
        self.assertEqual(id_, "10951")
        self.assertEqual(titolo, "Fahrenheit_451")

    def test_suddivisione_fino_a_soglia(self):
        # Con max_size basso l'albero deve scendere finche' ogni foglia sta
        # sotto soglia, senza perdere ne' duplicare voci.
        tuple_sql = ",".join(
            "(%d,0,'Voce_%04d',0)" % (i, i) for i in range(1, 501)
        )
        page = self._dump("INSERT INTO `page` VALUES %s;\n" % tuple_sql)
        langlinks = self._dump("INSERT INTO `langlinks` VALUES (9999,'it','X');\n")

        cwb.build(page, langlinks, self.root, max_size=50)

        righe = self._tutte()
        self.assertEqual(len(righe), 500)
        self.assertEqual(len(set(righe)), 500)
        for dirpath, _, files in os.walk(self.root):
            if "list.txt" in files:
                with open(os.path.join(dirpath, "list.txt"), encoding="utf-8") as fh:
                    n = len([r for r in fh.read().splitlines() if r])
                self.assertLess(n, 50, dirpath)

    def test_nessun_nodo_ibrido(self):
        # Una cartella o ha list.txt, o ha sottocartelle: mai entrambi,
        # altrimenti le stesse voci si conterebbero due volte.
        tuple_sql = ",".join(
            "(%d,0,'Voce_%04d',0)" % (i, i) for i in range(1, 401)
        )
        page = self._dump("INSERT INTO `page` VALUES %s;\n" % tuple_sql)
        langlinks = self._dump("INSERT INTO `langlinks` VALUES (9999,'it','X');\n")

        cwb.build(page, langlinks, self.root, max_size=20)

        for dirpath, dirs, files in os.walk(self.root):
            if dirpath == self.root:
                dirs[:] = [d for d in dirs if d != state.STATE_DIR]
            if "list.txt" in files:
                self.assertEqual(dirs, [], "nodo ibrido: %s" % dirpath)

    def test_staging_rimosso_a_fine_run(self):
        page = self._dump("INSERT INTO `page` VALUES (1,0,'Elsa',0);\n")
        langlinks = self._dump("INSERT INTO `langlinks` VALUES (2,'it','X');\n")

        cwb.build(page, langlinks, self.root)

        self.assertFalse(
            os.path.exists(os.path.join(self.root, cwb.STAGING_DIR)),
            "lo staging non e' stato rimosso",
        )

    def test_run_ripetuta_non_duplica(self):
        page = self._dump("INSERT INTO `page` VALUES (1,0,'Elsa',0);\n")
        langlinks = self._dump("INSERT INTO `langlinks` VALUES (2,'it','X');\n")

        cwb.build(page, langlinks, self.root)
        cwb.build(page, langlinks, self.root)

        self.assertEqual(self._tutte(), ["1\tElsa"])


class TestRipresa(unittest.TestCase):
    """La ripresa deve dare esattamente lo stesso output di un run intero."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.files = []

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)
        for path in self.files:
            if os.path.exists(path):
                os.unlink(path)

    def _dump(self, sql):
        fd, path = tempfile.mkstemp(suffix=".sql.gz")
        os.close(fd)
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            fh.write(sql)
        self.files.append(path)
        return path

    def _dataset(self, n=2000):
        page = self._dump(
            "INSERT INTO `page` VALUES %s;\n"
            % ",".join("(%d,0,'Voce_%05d',0)" % (i, i) for i in range(1, n + 1))
        )
        # un terzo delle voci ha gia' la versione italiana
        ll = self._dump(
            "INSERT INTO `langlinks` VALUES %s;\n"
            % ",".join("(%d,'it','X')" % i for i in range(1, n + 1, 3))
        )
        return page, ll

    def _righe(self, root, staging=False):
        """Le righe delle foglie definitive. Con `staging` legge invece i
        file intermedi della fase 2, che a run concluso non esistono piu'."""
        out = []
        for dirpath, dirs, files in os.walk(root):
            if dirpath == root:
                # Lo staging e' un partizionamento provvisorio: le sue righe
                # non sono output finale e conterebbero doppio.
                dirs[:] = [
                    d for d in dirs
                    if (d == cwb.STAGING_DIR) == staging and d != state.STATE_DIR
                ]
            if "list.txt" not in files:
                continue
            with open(os.path.join(dirpath, "list.txt"), encoding="utf-8") as fh:
                out.extend(r for r in fh.read().splitlines() if r)
        return sorted(out)

    def test_ripresa_fase2_equivale_a_run_intero(self):
        page, ll = self._dataset()

        atteso_root = os.path.join(self.root, "intero")
        cwb.build(page, ll, atteso_root, max_size=100)
        atteso = self._righe(atteso_root)

        # Interruzione durante la scansione (fase 2), iniettata nel writer
        # di staging.
        parziale = os.path.join(self.root, "parziale")

        original = cwb.StagingWriter.write
        stato = {"n": 0}

        def write_che_si_interrompe(self, title, page_id):
            stato["n"] += 1
            if stato["n"] > 700:
                raise KeyboardInterrupt
            return original(self, title, page_id)

        cwb.StagingWriter.write = write_che_si_interrompe
        try:
            with self.assertRaises(KeyboardInterrupt):
                cwb.build(page, ll, parziale, checkpoint_every=100, max_size=100)
        finally:
            cwb.StagingWriter.write = original

        # L'interruzione e' caduta prima della fase 3: c'e' staging, ma
        # nessuna foglia definitiva.
        self.assertGreater(len(self._righe(parziale, staging=True)), 0)
        self.assertEqual(self._righe(parziale), [])

        # La ripresa completa il lavoro senza duplicare ne' perdere righe.
        cwb.build(page, ll, parziale, checkpoint_every=100, max_size=100)
        ottenuto = self._righe(parziale)
        self.assertEqual(ottenuto, atteso)
        self.assertEqual(len(ottenuto), len(set(ottenuto)), "righe duplicate")

    def test_ripresa_fase3_equivale_a_run_intero(self):
        # Titoli su iniziali diverse: la fase 3 lavora un bucket alla volta,
        # quindi servono piu' bucket perche' ci sia un "a meta'".
        n = 2000
        page = self._dump(
            "INSERT INTO `page` VALUES %s;\n"
            % ",".join(
                "(%d,0,'%s_voce_%05d',0)" % (i, chr(97 + i % 26), i)
                for i in range(1, n + 1)
            )
        )
        ll = self._dump(
            "INSERT INTO `langlinks` VALUES %s;\n"
            % ",".join("(%d,'it','X')" % i for i in range(1, n + 1, 3))
        )

        atteso_root = os.path.join(self.root, "intero")
        cwb.build(page, ll, atteso_root, max_size=100)
        atteso = self._righe(atteso_root)

        # Interruzione a meta' della fase 3, dopo che qualche bucket e' gia'
        # stato suddiviso.
        parziale = os.path.join(self.root, "parziale")

        original = cwb.write_leaves
        stato = {"n": 0}

        def leaves_che_si_interrompono(root, leaves):
            stato["n"] += 1
            if stato["n"] > 3:
                raise KeyboardInterrupt
            return original(root, leaves)

        cwb.write_leaves = leaves_che_si_interrompono
        try:
            with self.assertRaises(KeyboardInterrupt):
                cwb.build(page, ll, parziale, max_size=100)
        finally:
            cwb.write_leaves = original

        # Qualche foglia c'e' gia', ma non tutte.
        self.assertGreater(len(self._righe(parziale)), 0)
        self.assertLess(len(self._righe(parziale)), len(atteso))

        cwb.build(page, ll, parziale, max_size=100)
        ottenuto = self._righe(parziale)
        self.assertEqual(ottenuto, atteso)
        self.assertEqual(len(ottenuto), len(set(ottenuto)), "righe duplicate")

    def test_riuso_del_file_intermedio_langlinks(self):
        page, ll = self._dataset(n=300)
        out = os.path.join(self.root, "o")
        cwb.build(page, ll, out)

        self.assertIsNotNone(state.load_ids(out), "gli id non sono stati salvati")

        # Un secondo run non deve piu' toccare il dump langlinks: lo si
        # verifica rendendolo illeggibile.
        os.unlink(ll)
        self.files.remove(ll)
        cwb.build(page, "dump-inesistente.sql.gz", out)
        self.assertEqual(len(self._righe(out)), 200)

    def test_progresso_azzerato_a_fine_run(self):
        page, ll = self._dataset(n=300)
        out = os.path.join(self.root, "o")
        cwb.build(page, ll, out)
        # Se restasse un checkpoint, un run successivo salterebbe tutto.
        self.assertEqual(state.load_progress(out), (0, 0, {}))

    def test_restart_ignora_lo_stato(self):
        page, ll = self._dataset(n=300)
        out = os.path.join(self.root, "o")
        cwb.build(page, ll, out)
        atteso = self._righe(out)

        state.save_progress(out, 999999, 999999, {})
        cwb.build(page, ll, out, resume=False)
        self.assertEqual(self._righe(out), atteso)

    def test_rollback_taglia_le_righe_oltre_il_checkpoint(self):
        out = os.path.join(self.root, "o")
        path = buckets.bucket_path(out, ("a", "b"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("1\tUno\n2\tDue\n")
        checkpoint = os.path.getsize(path)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("3\tTre\n")

        rel = os.path.relpath(path, out)
        dropped = state.rollback_to_checkpoint(out, {rel: checkpoint})

        self.assertGreater(dropped, 0)
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "1\tUno\n2\tDue\n")


class TestRicercaBinaria(unittest.TestCase):
    def test_trova_e_non_trova(self):
        ids = [1, 5, 9, 100, 5000]
        for i in ids:
            self.assertTrue(cwb.has_italian(ids, i))
        for i in (0, 2, 50, 99, 4999, 5001):
            self.assertFalse(cwb.has_italian(ids, i))

    def test_lista_vuota(self):
        self.assertFalse(cwb.has_italian([], 42))


class TestStagingWriter(unittest.TestCase):
    def test_partiziona_per_primo_carattere(self):
        root = tempfile.mkdtemp()
        try:
            writer = cwb.StagingWriter(root)
            titoli = ["Alpha", "Beta", "Gamma", "Àlpino", "1984", "東京"]
            for n, titolo in enumerate(titoli):
                writer.write(titolo, n)
            writer.close()

            # 'Àlpino' finisce con 'Alpha' grazie a NFKD; '1984' fa bucket
            # a se' fra le cifre; '東京' cade in "altro".
            self.assertEqual(self._righe(root, "a"), ["0\tAlpha", "3\tÀlpino"])
            self.assertEqual(self._righe(root, "1"), ["4\t1984"])
            self.assertEqual(self._righe(root, "_"), ["5\t東京"])

            totale = sum(
                len(self._righe(root, s)) for s in buckets.BUCKET_CHARS
            )
            self.assertEqual(totale, len(titoli))
        finally:
            shutil.rmtree(root)

    def _righe(self, root, symbol):
        path = cwb.staging_path(root, symbol)
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as fh:
            return [r for r in fh.read().splitlines() if r]


class TestGrouping(unittest.TestCase):
    """Accorpamento dei batch in groups/."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.batches = os.path.join(self.root, "batches")
        self.out = os.path.join(self.root, "groups")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _batch(self, rel, righe):
        """Crea un batch con `righe` voci, o con contenuto grezzo se bytes."""
        d = os.path.join(self.batches, *rel.split("/"))
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "list.txt")
        if isinstance(righe, bytes):
            with open(path, "wb") as fh:
                fh.write(righe)
            return
        with open(path, "w", encoding="utf-8") as fh:
            for i in righe:
                fh.write("%d\tVoce_%05d\n" % (i, i))

    def _gruppi(self):
        return sorted(
            f for f in os.listdir(self.out)
            if f.endswith(".txt") and f != grouping.INDEX_NAME
        )

    def _righe(self, name):
        with open(os.path.join(self.out, name), encoding="utf-8") as fh:
            return [r for r in fh.read().splitlines() if r]

    def test_accorpa_finche_entra(self):
        # Quattro batch piccoli stanno tutti in un gruppo solo.
        for n, rel in enumerate(["a/a", "a/b", "b/a", "c/c"]):
            self._batch(rel, range(n * 10, n * 10 + 10))

        grouping.build(self.batches, self.out, max_size=1000)

        self.assertEqual(len(self._gruppi()), 1)
        self.assertEqual(len(self._righe(self._gruppi()[0])), 40)

    def test_chiude_il_gruppo_alla_soglia(self):
        # Due batch da 60: con soglia 100 non possono stare insieme.
        self._batch("a/a", range(60))
        self._batch("a/b", range(100, 160))

        grouping.build(self.batches, self.out, max_size=100)

        self.assertEqual(len(self._gruppi()), 2)
        for name in self._gruppi():
            self.assertLess(len(self._righe(name)), 100)

    def test_nessun_gruppo_raggiunge_la_soglia(self):
        for i in range(40):
            self._batch("%02d" % i, range(i * 100, i * 100 + 30))

        grouping.build(self.batches, self.out, max_size=100)

        for name in self._gruppi():
            self.assertLess(len(self._righe(name)), 100, name)

    def test_conservazione_delle_voci(self):
        attese = []
        for i in range(30):
            righe = list(range(i * 50, i * 50 + 20))
            attese.extend("%d\tVoce_%05d" % (n, n) for n in righe)
            self._batch("b%02d" % i, righe)

        grouping.build(self.batches, self.out, max_size=100)

        ottenute = []
        for name in self._gruppi():
            ottenute.extend(self._righe(name))
        self.assertEqual(sorted(ottenute), sorted(attese))
        self.assertEqual(len(ottenute), len(set(ottenute)), "voci duplicate")

    def test_giunzione_senza_newline_finale(self):
        # Regressione: senza il \n aggiunto, '2\tDue' e '3\tTre' si
        # salderebbero in '2\tDue3\tTre' -- una riga che ha comunque un TAB
        # e quindi passerebbe un controllo di formato superficiale.
        self._batch("a", b"1\tUno\n2\tDue")
        self._batch("b", b"3\tTre\n")

        grouping.build(self.batches, self.out, max_size=1000)

        righe = self._righe(self._gruppi()[0])
        self.assertEqual(righe, ["1\tUno", "2\tDue", "3\tTre"])
        for riga in righe:
            self.assertEqual(riga.count("\t"), 1, riga)

    def test_ogni_gruppo_termina_con_newline(self):
        self._batch("a", b"1\tUno\n2\tDue")
        self._batch("b", b"3\tTre")

        grouping.build(self.batches, self.out, max_size=1000)

        for name in self._gruppi():
            with open(os.path.join(self.out, name), "rb") as fh:
                self.assertTrue(fh.read().endswith(b"\n"), name)

    def test_batch_vuoto_non_rompe_il_conteggio(self):
        self._batch("a", range(10))
        self._batch("b", b"")
        self._batch("c", range(100, 110))

        grouping.build(self.batches, self.out, max_size=1000)

        self.assertEqual(len(self._righe(self._gruppi()[0])), 20)

    def test_nome_col_prefisso_del_primo(self):
        self._batch("l/i/s", range(10))

        grouping.build(self.batches, self.out, max_size=1000)

        # Percorso del primo batch, senza separatori.
        self.assertEqual(self._gruppi(), ["1-lis.txt"])

    def test_indice_elenca_esattamente_i_gruppi(self):
        for i in range(50):
            self._batch("b%02d" % i, range(i * 50, i * 50 + 30))

        grouping.build(self.batches, self.out, max_size=100)

        with open(os.path.join(self.out, grouping.INDEX_NAME), encoding="utf-8") as fh:
            elencati = [r for r in fh.read().splitlines() if r]
        self.assertEqual(sorted(elencati), self._gruppi())

    def test_out_cancellato_prima_di_ricominciare(self):
        self._batch("a", range(10))
        os.makedirs(self.out, exist_ok=True)
        intruso = os.path.join(self.out, "9999-vecchio.txt")
        with open(intruso, "w", encoding="utf-8") as fh:
            fh.write("1\tResiduo\n")

        grouping.build(self.batches, self.out, max_size=1000)

        self.assertFalse(os.path.exists(intruso), "residuo di un run precedente")

    def test_ripetibile_byte_per_byte(self):
        for i in range(30):
            self._batch("b%02d" % i, range(i * 50, i * 50 + 20))

        grouping.build(self.batches, self.out, max_size=100)
        primo = {n: open(os.path.join(self.out, n), "rb").read()
                 for n in os.listdir(self.out)}

        grouping.build(self.batches, self.out, max_size=100)
        secondo = {n: open(os.path.join(self.out, n), "rb").read()
                   for n in os.listdir(self.out)}

        self.assertEqual(primo, secondo)

    def test_batches_non_viene_modificato(self):
        self._batch("a", range(10))
        prima = open(os.path.join(self.batches, "a", "list.txt"), "rb").read()

        grouping.build(self.batches, self.out, max_size=1000)

        dopo = open(os.path.join(self.batches, "a", "list.txt"), "rb").read()
        self.assertEqual(prima, dopo)

    def test_albero_vuoto_e_un_errore(self):
        os.makedirs(self.batches, exist_ok=True)
        with self.assertRaises(ValueError):
            grouping.build(self.batches, self.out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
