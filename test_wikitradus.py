#!/usr/bin/env python3
"""Test per wikitradus: scelta del modello e traduzione a lotti.
Eseguire con: python3 -m unittest test_wikitradus -v"""

import tempfile
import types
import unittest
from pathlib import Path

from unittest import mock

from wikitradus.cli import ASSISTANTS, Assistant, _looks_like_bad_model
from wikitradus.extract import RateLimited
from wikitradus import translate
from wikitradus.translate import (
    MARKER,
    make_batches,
    split_batch_answer,
)


class TestModelloEdEffort(unittest.TestCase):
    """Il modello e' scelto dal progetto, non dalla configurazione locale."""

    def _comando(self, name, model=None, effort=None):
        assistant = Assistant(name, ASSISTANTS[name], model, effort)
        return assistant._build("PROMPT", assistant.model, assistant.effort)

    def test_default_codex(self):
        comando = self._comando("codex")
        self.assertIn("gpt-5.4-mini", comando)
        self.assertIn("model_reasoning_effort=low", comando)

    def test_default_claude(self):
        comando = self._comando("claude")
        self.assertIn("claude-haiku-4-5", comando)

    def test_override_modello(self):
        comando = self._comando("codex", model="gpt-5.5")
        self.assertIn("gpt-5.5", comando)
        self.assertNotIn("gpt-5.4-mini", comando)

    def test_override_effort(self):
        comando = self._comando("codex", effort="high")
        self.assertIn("model_reasoning_effort=high", comando)

    def test_claude_ignora_effort(self):
        # 'claude' non ha un flag di reasoning effort: passarlo non deve
        # comparire nel comando ne' far fallire la costruzione.
        comando = self._comando("claude", effort="xhigh")
        self.assertNotIn("xhigh", comando)
        self.assertIn("claude-haiku-4-5", comando)

    def test_il_prompt_resta_ultimo(self):
        # Il prompt e' posizionale: se finisse prima di un flag verrebbe letto
        # come valore di quel flag.
        for name in ASSISTANTS:
            with self.subTest(cli=name):
                self.assertEqual(self._comando(name)[-1], "PROMPT")


class TestIsolamentoDalRepo(unittest.TestCase):
    """La CLI non deve vedere i file del clone.

    Entrambe le CLI leggono CLAUDE.md / AGENTS.md dalla directory da cui
    partono, e il clone ne contiene uno con le regole di questo repository:
    istruzioni estranee alla traduzione, che occuperebbero contesto in ogni
    chiamata e potrebbero spingere la CLI a fare altro.
    """

    def _esegui(self):
        """Restituisce (cwd, contenuto) osservati mentre la CLI 'gira'."""
        visto = {}

        def spia(*args, **kwargs):
            cwd = Path(kwargs["cwd"])
            # Va guardata adesso: al ritorno di ask() e' gia' stata rimossa.
            visto["cwd"] = cwd
            visto["contenuto"] = sorted(p.name for p in cwd.iterdir())
            return types.SimpleNamespace(returncode=0, stdout="ok", stderr="")

        assistant = Assistant("codex", ASSISTANTS["codex"])
        with mock.patch("wikitradus.cli.subprocess.run", side_effect=spia):
            assistant.ask("prompt")
        return visto

    def test_gira_in_una_directory_vuota(self):
        self.assertEqual(self._esegui()["contenuto"], [])

    def test_non_gira_nel_repository(self):
        cwd = self._esegui()["cwd"].resolve()
        progetto = Path(__file__).resolve().parent
        self.assertFalse(
            cwd == progetto or progetto in cwd.parents or cwd in progetto.parents,
            f"la CLI verrebbe eseguita dentro il repository: {cwd}",
        )

    def test_la_directory_viene_rimossa(self):
        # Una per chiamata: non devono accumularsi sul disco a ogni voce.
        self.assertFalse(self._esegui()["cwd"].exists())


class TestRiconoscimentoModelloIgnoto(unittest.TestCase):
    """Messaggi osservati sul campo, non inventati."""

    def test_codex_modello_inesistente(self):
        self.assertTrue(_looks_like_bad_model(
            'ERROR: {"type":"error","status":400,"error":{"type":'
            '"invalid_request_error","message":"The \'gpt-nonexistent-9\' model '
            'is not supported when using Codex with a ChatGPT account."}}'
        ))

    def test_codex_effort_inesistente(self):
        self.assertTrue(_looks_like_bad_model(
            "Error loading config.toml: unknown variant `nonesuch`, expected "
            "one of `none`, `minimal`, `low`, `medium`, `high`, `xhigh`"
        ))

    def test_claude_modello_inesistente(self):
        self.assertTrue(_looks_like_bad_model(
            "There's an issue with the selected model (modello-inesistente-9). "
            "It may not exist or you may not have access to it."
        ))

    def test_non_confonde_altri_errori(self):
        # Una sessione scaduta non e' un modello sbagliato: deve restare sul
        # percorso dell'autenticazione.
        self.assertFalse(_looks_like_bad_model("Not logged in. Run codex login."))
        self.assertFalse(_looks_like_bad_model("network unreachable"))


class TestComposizioneLotti(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _file(self, name, size):
        path = self.dir / f"{name}.md"
        path.write_text("x" * size)
        return path

    def test_raggruppa_fino_alla_soglia(self):
        paths = [self._file(str(i), 1000) for i in range(5)]
        lotti = make_batches(paths, max_bytes=2500, max_entries=99)
        self.assertEqual([len(l) for l in lotti], [2, 2, 1])

    def test_tetto_sul_numero_di_voci(self):
        paths = [self._file(str(i), 10) for i in range(7)]
        lotti = make_batches(paths, max_bytes=100_000, max_entries=3)
        self.assertEqual([len(l) for l in lotti], [3, 3, 1])

    def test_voce_sopra_soglia_va_da_sola(self):
        # La voce piu' lunga misurata era 27 KB, sopra la soglia di lotto: deve
        # partire da sola invece di bloccare il raggruppamento.
        grande = self._file("grande", 30_000)
        piccola = self._file("piccola", 500)
        lotti = make_batches([grande, piccola], max_bytes=24_000)
        self.assertEqual(lotti, [[grande], [piccola]])

    def test_nessun_file(self):
        self.assertEqual(make_batches([]), [])

    def test_non_perde_voci(self):
        paths = [self._file(str(i), 900) for i in range(11)]
        lotti = make_batches(paths, max_bytes=2000, max_entries=4)
        self.assertEqual([p for lotto in lotti for p in lotto], paths)


class TestSplitRisposta(unittest.TestCase):
    def _risposta(self, coppie):
        return "\n\n".join(
            f"{MARKER.format(page_id=pid)}\n{testo}" for pid, testo in coppie
        )

    def test_risposta_completa(self):
        answer = self._risposta([("11", "Prima voce"), ("22", "Seconda voce")])
        self.assertEqual(
            split_batch_answer(answer, ["11", "22"]),
            {"11": "Prima voce", "22": "Seconda voce"},
        )

    def test_blocco_mancante(self):
        # Il chiamante ritraduce da sola la voce assente.
        answer = self._risposta([("11", "Prima voce")])
        self.assertEqual(
            split_batch_answer(answer, ["11", "22"]), {"11": "Prima voce"}
        )

    def test_identificativo_inatteso_scartato(self):
        # Accettarlo significherebbe scrivere una traduzione sul file sbagliato.
        answer = self._risposta([("11", "Prima"), ("999", "Voce mai inviata")])
        self.assertEqual(split_batch_answer(answer, ["11", "22"]), {"11": "Prima"})

    def test_identificativo_ripetuto_scartato(self):
        # Due blocchi per la stessa voce: senza sapere quale sia quello buono,
        # meglio ritradurla che indovinare.
        answer = self._risposta([("11", "Una versione"), ("11", "Un'altra")])
        self.assertEqual(split_batch_answer(answer, ["11"]), {})

    def test_ordine_invertito(self):
        # I delimitatori portano l'identificativo, quindi l'ordine non conta.
        answer = self._risposta([("22", "Seconda"), ("11", "Prima")])
        self.assertEqual(
            split_batch_answer(answer, ["11", "22"]),
            {"11": "Prima", "22": "Seconda"},
        )

    def test_nessun_delimitatore(self):
        # La CLI ha ignorato il formato: niente e' recuperabile.
        self.assertEqual(
            split_batch_answer("Solo testo tradotto", ["11", "22"]), {}
        )

    def test_blocco_vuoto_scartato(self):
        answer = self._risposta([("11", ""), ("22", "Seconda")])
        self.assertEqual(split_batch_answer(answer, ["11", "22"]), {"22": "Seconda"})

    def test_risposta_dentro_code_fence(self):
        # La CLI incornicia il risultato nonostante la richiesta contraria.
        inner = self._risposta([("11", "Prima"), ("22", "Seconda")])
        answer = f"```markdown\n{inner}\n```"
        self.assertEqual(
            split_batch_answer(answer, ["11", "22"]),
            {"11": "Prima", "22": "Seconda"},
        )

    def test_markdown_interno_conservato(self):
        testo = "# Titolo\n\n**grassetto** e *corsivo*\n\n- uno\n- due"
        answer = self._risposta([("11", testo)])
        self.assertEqual(split_batch_answer(answer, ["11"]), {"11": testo})

    def test_delimitatore_con_spaziatura_diversa(self):
        # La CLI puo' riemettere il delimitatore con un numero di '=' diverso.
        answer = "=== VOCE 11 ===\nPrima voce"
        self.assertEqual(split_batch_answer(answer, ["11"]), {"11": "Prima voce"})

    def test_preambolo_ignorato(self):
        # Il testo prima del primo delimitatore non appartiene a nessuna voce:
        # attaccarlo alla prima la sporcherebbe.
        answer = "Ecco le traduzioni:\n\n" + self._risposta([("11", "Prima")])
        self.assertEqual(split_batch_answer(answer, ["11"]), {"11": "Prima"})

    def test_delimitatore_finale_senza_corpo(self):
        # Risposta troncata a meta': l'ultima voce non e' tradotta e va ripresa.
        answer = self._risposta([("11", "Prima")]) + "\n\n" + MARKER.format(page_id="22")
        self.assertEqual(split_batch_answer(answer, ["11", "22"]), {"11": "Prima"})

    def test_identificativo_non_numerico(self):
        answer = self._risposta([("1-2_3", "Testo")])
        self.assertEqual(split_batch_answer(answer, ["1-2_3"]), {"1-2_3": "Testo"})


class TestEtichettaVoce(unittest.TestCase):
    """Nei messaggi compare il titolo, non il numero del file."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _file(self, name, testo):
        path = self.dir / f"{name}.md"
        path.write_text(testo)
        return path

    def test_legge_il_titolo_dall_intestazione(self):
        path = self._file("123", "# Get Happy\n\n*[Voce originale](...)*\n\ntesto")
        self.assertEqual(translate._label(path), "Get Happy")

    def test_senza_intestazione_ripiega_sul_nome(self):
        path = self._file("456", "testo senza intestazione")
        self.assertEqual(translate._label(path), "456")

    def test_file_vuoto(self):
        self.assertEqual(translate._label(self._file("789", "")), "789")

    def test_file_inesistente(self):
        # Non deve sollevare: e' solo un'etichetta per un messaggio.
        self.assertEqual(translate._label(self.dir / "000.md"), "000")

    def test_usa_il_testo_gia_letto(self):
        # Passando il contenuto non si rilegge il file da disco.
        path = self.dir / "111.md"
        self.assertEqual(translate._label(path, "# Titolo\n\ntesto"), "Titolo")


class TestCommitPerLotto(unittest.TestCase):
    """Si pubblica alla fine di ogni lotto, non ogni N voci."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

        # Lotti da 3 voci, cosi' con 7 voci se ne producono tre.
        for name, value in (("BATCH_MAX_ENTRIES", 3), ("FETCH_PAUSE", 0)):
            patcher = mock.patch.object(translate, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.commits = []
        self.tradotte = 0
        self.pubblicate = 0

        def commit_all(message):
            # Come il vero commit_all: senza nulla di nuovo restituisce False.
            if self.pubblicate == self.tradotte:
                return False
            self.pubblicate = self.tradotte
            self.commits.append(message)
            return True

        self.workdir = types.SimpleNamespace(
            path=self.dir,
            group_dir=lambda g: self.dir / g,
            translated_ids=lambda g: set(),
            mark_translated=lambda g, pid: None,
            commit_all=commit_all,
            push=lambda: None,
        )

        def fake_batch(paths, assistant):
            for path in paths:
                path.write_text("(tradotto)\n")
            self.tradotte += len(paths)
            return list(paths)

        for name, value in (
            ("_translate_batch", fake_batch),
            ("_fetch_with_retry", lambda t, l: "<div class='mw-parser-output'><p>x</p></div>"),
        ):
            patcher = mock.patch.object(translate, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _esegui(self, quante):
        voci = [(str(i), f"Voce_{i}") for i in range(1, quante + 1)]
        return translate.process_group(
            self.workdir, "t", voci, types.SimpleNamespace(name="codex")
        )

    def test_un_commit_per_lotto(self):
        # 7 voci in lotti da 3: tre lotti, tre commit. Con la vecchia regola
        # (ogni 10) non ce ne sarebbe stato nessuno fino alla fine.
        self._esegui(7)
        self.assertEqual(len(self.commits), 3)

    def test_il_commit_riporta_il_totale_progressivo(self):
        self._esegui(7)
        self.assertEqual(
            self.commits,
            [
                "traduzioni: t, 3 voci",
                "traduzioni: t, 6 voci",
                "traduzioni: t, 7 voci",
            ],
        )

    def test_nessun_commit_duplicato_alla_fine(self):
        # L'ultimo lotto ha gia' pubblicato: la chiusura non ripete lo stesso
        # stato, perche' commit_all vede che non c'e' nulla di nuovo.
        self._esegui(6)
        self.assertEqual(self.commits[-1], "traduzioni: t, 6 voci")
        self.assertEqual(len(self.commits), 2)

    def test_lotto_senza_traduzioni_non_committa(self):
        # Se la CLI non rende nulla non si crea un commit vuoto.
        with mock.patch.object(
            translate, "_translate_batch", lambda p, a: []
        ), mock.patch.object(translate, "_translate_one", lambda p, a: False):
            self._esegui(4)
        self.assertEqual(self.commits, [])


class TestRateLimitWikipedia(unittest.TestCase):
    """Un 429 e' una richiesta di rallentare, non la fine del lavoro."""

    def setUp(self):
        # Le attese non devono rallentare i test.
        patcher = mock.patch.object(translate.time, "sleep")
        self.sleep = patcher.start()
        self.addCleanup(patcher.stop)

    def test_riprova_dopo_il_429(self):
        with mock.patch.object(
            translate, "fetch_html",
            side_effect=[RateLimited("429", 5), "<html>ok</html>"],
        ):
            self.assertEqual(
                translate._fetch_with_retry("Voce", "en"), "<html>ok</html>"
            )
        self.sleep.assert_called_once_with(5)

    def test_usa_il_retry_after_del_server(self):
        # L'attesa indicata da Wikipedia vince sulla nostra.
        with mock.patch.object(
            translate, "fetch_html",
            side_effect=[RateLimited("429", 42), "ok"],
        ):
            translate._fetch_with_retry("Voce", "en")
        self.sleep.assert_called_once_with(42)

    def test_senza_retry_after_attesa_crescente(self):
        with mock.patch.object(
            translate, "fetch_html",
            side_effect=[RateLimited("429"), RateLimited("429"), "ok"],
        ):
            translate._fetch_with_retry("Voce", "en")
        self.assertEqual(
            [c.args[0] for c in self.sleep.call_args_list],
            [translate.RATE_LIMIT_PAUSE, translate.RATE_LIMIT_PAUSE * 2],
        )

    def test_si_arrende_se_il_limite_persiste(self):
        # Esauriti i tentativi l'errore risale: il gruppo si ferma e riprende
        # dopo, invece di insistere all'infinito.
        with mock.patch.object(
            translate, "fetch_html",
            side_effect=RateLimited("429", 1),
        ):
            with self.assertRaises(RateLimited):
                translate._fetch_with_retry("Voce", "en")

    def test_altri_errori_non_vengono_ritentati(self):
        with mock.patch.object(
            translate, "fetch_html", side_effect=ValueError("rotto"),
        ) as fetch:
            with self.assertRaises(ValueError):
                translate._fetch_with_retry("Voce", "en")
        self.assertEqual(fetch.call_count, 1)


if __name__ == "__main__":
    unittest.main()
