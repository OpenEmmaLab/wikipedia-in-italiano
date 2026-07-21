#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = ["beautifulsoup4", "markdownify", "requests"]
# ///
"""Estrae una voce di Wikipedia e la converte in markdown.

Scarica l'HTML renderizzato dall'endpoint REST, isola il contenuto utile dal
container `mw-parser-output` e lo converte con markdownify. È il passo di
estrazione descritto nella issue #3, isolato per poterlo provare su singole voci.

    ./extract.py 141st_New_York_Infantry_Regiment
    ./extract.py 141st_meridian_east --lang it

Il titolo è quello che compare nella seconda colonna dei file in groups/, già
nel formato con underscore accettato dall'endpoint.
"""
import argparse
import sys

import requests
from bs4 import BeautifulSoup
from markdownify import markdownify

REST_URL = "https://{lang}.wikipedia.org/w/rest.php/v1/page/{title}/html"
USER_AGENT = "wikipedia-in-italiano/0.1 (https://github.com/OpenEmmaLab/wikipedia-in-italiano)"


def fetch_html(title, lang="en"):
    """Scarica l'HTML renderizzato della voce. None se la voce non esiste."""
    url = REST_URL.format(lang=lang, title=title)
    response = requests.get(url, headers={"User-Agent": USER_AGENT})
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.text


def to_markdown(html):
    """Isola mw-parser-output e converte in markdown."""
    soup = BeautifulSoup(html, "html.parser")
    content = soup.select_one(".mw-parser-output")
    if content is None:
        raise ValueError("container mw-parser-output non trovato")
    return markdownify(str(content), heading_style="ATX")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("title", help="titolo della voce, con gli underscore")
    parser.add_argument("--lang", default="en", help="lingua di partenza (default: en)")
    args = parser.parse_args()

    html = fetch_html(args.title, args.lang)
    if html is None:
        # Voce cancellata o rinominata dopo la generazione dei batch: si salta.
        print(f"{args.title}: voce non trovata (404)", file=sys.stderr)
        return 1

    print(to_markdown(html))
    return 0


if __name__ == "__main__":
    sys.exit(main())
