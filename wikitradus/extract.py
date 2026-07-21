"""Estrazione di voci di Wikipedia in markdown.

Scarica l'HTML renderizzato dall'endpoint REST, isola il contenuto utile dal
container `mw-parser-output`, rimuove tutto ciò che non è prosa dell'articolo e
converte il resto in markdown.
"""
import re
import sys
import urllib.parse
import urllib.request

from bs4 import BeautifulSoup
from markdownify import markdownify

REST_URL = "https://{lang}.wikipedia.org/w/rest.php/v1/page/{title}/html"
USER_AGENT = (
    "wikipedia-in-italiano/0.1 "
    "(https://github.com/OpenEmmaLab/wikipedia-in-italiano)"
)

# Blocchi che non sono prosa dell'articolo e non vanno tradotti.
# I selettori sono verificati sull'HTML reale delle voci del gruppo 0001-0.
DROP_SELECTORS = [
    # Avvisi di manutenzione: "This section needs more citations…"
    ".ambox", ".mbox-text", ".ombox", ".tmbox", ".cmbox", ".fmbox",
    # Avviso di disambiguazione: "Topics referred to by the same term…"
    ".dmbox", ".metadata",
    # Navigazione e rimandi
    ".navbox", ".sidebar", ".vertical-navbox", ".hatnote", ".sistersitebox",
    ".shortdescription", ".navigation-not-searchable",
    # Immagini e contenuti multimediali
    "figure", ".thumb", ".gallery", "img", ".mw-file-element",
    ".mw-file-description", ".mw-default-size", ".flagicon", ".mw-image-border",
    # Infobox
    ".infobox", ".infobox-label", ".infobox-data", ".infobox-image",
    # Apparato tecnico
    "sup.reference", ".mw-references-wrap", ".reflist", ".mw-editsection",
    ".noprint", ".mw-empty-elt", "style", "link", "meta",
]

# Sezioni finali da rimuovere per intero, intestazione compresa. "See also" non
# c'è: nelle pagine di disambiguazione è il contenuto stesso della voce.
DROP_SECTIONS = {
    "references", "reference", "external links", "external link",
    "further reading", "notes", "note", "bibliography", "sources", "source",
}


class NotFound(Exception):
    """La voce non esiste più su Wikipedia."""


def _get(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise NotFound(url) from exc
        raise


def fetch_html(title, lang="en"):
    """Scarica l'HTML renderizzato della voce. Solleva NotFound se non esiste."""
    # safe="" per codificare anche la slash: i titoli che la contengono
    # (06/05, 0/1-polytope) verrebbero altrimenti spezzati nel path.
    quoted = urllib.parse.quote(title.replace(" ", "_"), safe="")
    return _get(REST_URL.format(lang=lang, title=quoted))


def _drop_final_sections(root):
    """Rimuove References, External links e simili, intestazione compresa."""
    for section in root.find_all("section", recursive=False):
        heading = section.find(["h1", "h2", "h3"])
        if heading is None:
            continue
        name = " ".join(heading.get_text(" ", strip=True).split()).lower()
        if name in DROP_SECTIONS:
            section.decompose()


def _unlink(root):
    """Toglie tutti i link, interni ed esterni, conservandone il testo.

    Un link non aggiunge nulla al testo da tradurre: quelli interni sono
    relativi a Wikipedia e non risolvono altrove, quelli esterni portano fuori.
    Si scarta l'ancora e si tiene la parola, così la prosa resta intatta.
    """
    for anchor in root.find_all("a"):
        anchor.unwrap()


def to_markdown(html, lang="en"):
    """Isola il contenuto, rimuove ciò che non è prosa e converte in markdown."""
    soup = BeautifulSoup(html, "html.parser")
    root = soup.select_one(".mw-parser-output")
    if root is None:
        raise ValueError("container mw-parser-output non trovato")

    for selector in DROP_SELECTORS:
        for element in root.select(selector):
            element.decompose()
    _drop_final_sections(root)
    _unlink(root)

    markdown = markdownify(str(root), heading_style="ATX")
    # markdownify lascia lunghe sequenze di righe vuote dove sono stati tolti
    # i blocchi: le riduce a una riga vuota sola.
    return re.sub(r"\n{3,}", "\n\n", markdown).strip()


def extract(title, lang="en"):
    """Scarica una voce e la restituisce in markdown."""
    return to_markdown(fetch_html(title, lang), lang)


def main(argv):
    if len(argv) < 2:
        print("uso: extract.py <titolo> [lingua]", file=sys.stderr)
        return 2
    title = argv[1]
    lang = argv[2] if len(argv) > 2 else "en"
    try:
        print(extract(title, lang))
    except NotFound:
        print(f"{title}: voce non trovata (404)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
