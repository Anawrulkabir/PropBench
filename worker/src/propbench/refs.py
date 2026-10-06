"""References (README §2e.10): BibTeX import and export, DOI lookup, short citations for datasets and models.

A reference is a dict ``{"key", "type", "fields": {...}}`` (BibTeX fields, lower-case names). ``lookup_doi`` asks
Crossref's public API (https://api.crossref.org) and is the only function that uses the network; the fetcher can
be replaced (tests run offline).
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

DOI_PATTERN = re.compile(r"^10\.\d{4,9}/\S+$")


class RefError(ValueError):
    """A BibTeX text or DOI cannot be read."""


def _read_value(text: str, i: int) -> tuple[str, int]:
    """A field value starting at ``text[i]``: {braced}, "quoted" or a bare word/number; returns (value, end)."""
    if text[i] == "{":
        depth, j = 0, i
        while j < len(text):
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    return text[i + 1 : j], j + 1
            j += 1
        raise RefError("unbalanced braces in BibTeX")
    if text[i] == '"':
        j = i + 1
        while j < len(text) and (text[j] != '"' or text[j - 1] == "\\"):
            j += 1
        return text[i + 1 : j], j + 1
    m = re.match(r"[^,}\s]+", text[i:])
    if not m:
        raise RefError("empty BibTeX field value")
    return m.group(0), i + m.end()


def parse_bibtex(text: str) -> list[dict[str, Any]]:
    """Entries of a BibTeX text (``@comment``, ``@string`` and ``@preamble`` are skipped)."""
    out = []
    for m in re.finditer(r"@(\w+)\s*\{\s*([^,\s]+)\s*,", text):
        kind, key = m.group(1).lower(), m.group(2)
        if kind in ("comment", "string", "preamble"):
            continue
        fields: dict[str, str] = {}
        i = m.end()
        while i < len(text):
            while i < len(text) and text[i] in " \t\r\n,":
                i += 1
            if i >= len(text) or text[i] == "}":
                break
            fm = re.match(r"([\w\-]+)\s*=\s*", text[i:])
            if not fm:
                raise RefError(f"{key}: cannot read the field at {text[i : i + 30]!r}")
            i += fm.end()
            value, i = _read_value(text, i)
            fields[fm.group(1).lower()] = re.sub(r"\s+", " ", value.replace("{", "").replace("}", "")).strip()
        out.append({"key": key, "type": kind, "fields": fields})
    return out


def to_bibtex(refs: list[Mapping[str, Any]]) -> str:
    blocks = []
    for r in refs:
        body = ",\n".join(f"  {k} = {{{v}}}" for k, v in r["fields"].items())
        blocks.append(f"@{r.get('type', 'article')}{{{r['key']},\n{body}\n}}")
    return "\n\n".join(blocks) + "\n"


def citation(ref: Mapping[str, Any]) -> str:
    """Short citation, e.g. "Tuhin et al. (2024) Int. J. Thermophys. 45:41, doi:10.1007/..."."""
    f = ref.get("fields", {})
    authors = [a.strip() for a in f.get("author", "").split(" and ") if a.strip()]
    surname = lambda a: a.split(",")[0].strip() if "," in a else a.split()[-1]  # noqa: E731
    who = (
        ""
        if not authors
        else surname(authors[0])
        + (" et al." if len(authors) > 2 else (f" and {surname(authors[1])}" if len(authors) == 2 else ""))
    )
    where = " ".join(x for x in (f.get("journal", ""), f.get("volume", "")) if x)
    if f.get("pages"):
        where += f":{f['pages']}"
    parts = [p for p in (f"{who} ({f.get('year', 'n.d.')})" if who else f.get("year", ""), where) if p]
    text = " ".join(parts)
    return f"{text}, doi:{f['doi']}" if f.get("doi") else text


def _crossref(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "PropBench (https://github.com/anawrulkabir/PropBench)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def lookup_doi(doi: str, fetch: Callable[[str], bytes] = _crossref) -> dict[str, Any]:
    """Reference for a DOI from Crossref (title, authors, journal, volume, pages, year)."""
    doi = doi.strip().removeprefix("https://doi.org/").removeprefix("doi:")
    if not DOI_PATTERN.match(doi):
        raise RefError(f"{doi!r} is not a DOI")
    try:
        data = json.loads(fetch("https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="/")))["message"]
    except (OSError, ValueError, KeyError) as exc:
        raise RefError(f"DOI lookup failed for {doi}: {exc}") from exc
    authors = " and ".join(f"{a.get('family', '')}, {a.get('given', '')}".strip(", ") for a in data.get("author", []))
    year = (data.get("issued", {}).get("date-parts") or [[None]])[0][0]
    fields = {
        "title": (data.get("title") or [""])[0],
        "author": authors,
        "journal": (data.get("short-container-title") or data.get("container-title") or [""])[0],
        "volume": str(data.get("volume", "")),
        "pages": str(data.get("page") or data.get("article-number") or ""),
        "year": str(year or ""),
        "doi": doi,
    }
    first = (data.get("author") or [{}])[0].get("family", "ref")
    key = re.sub(r"\W", "", f"{first}{year or ''}") or "ref"
    return {"key": key, "type": "article", "fields": {k: v for k, v in fields.items() if v}}
