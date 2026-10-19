"""Compression rules 1.29.0 (CC002 quote_matching NORMALIZED): a quote or binding value matches its source when the
two agree after removing differences of letter case, spacing and the spelling of dashes, quotation marks and ±.
Digits, decimal points and words must still agree; a run frozen before 1.29.0 matches exactly."""
import re
import unicodedata
from functools import lru_cache

from .rules import host_requirement

SPELLINGS = str.maketrans({'‐': '-', '‑': '-', '‒': '-', '–': '-', '—': '-', '−': '-',
                           '“': '"', '”': '"', '„': '"', '‘': "'", '’': "'", '‚': "'"})
PLUS_MINUS = re.compile(r'\+\s*/\s*-|\+-(?=\s*\d)')
AROUND_SIGNS = re.compile(r'\s*([-/()\[\]{},;:=<>±%"\'])\s*')
EDGES = ' .,;:'


def loose(source):
    """Whether this run (a bundle or request payload) matches quotes after normalization."""
    return host_requirement(source, 'CC002').get('quote_matching') == 'NORMALIZED'


@lru_cache(maxsize=4096)
def normalized(text):
    text = unicodedata.normalize('NFKC', text).translate(SPELLINGS).casefold()
    text = PLUS_MINUS.sub('±', text)
    return AROUND_SIGNS.sub(r'\1', ' '.join(text.split()))


def contains(text, quote, loose=False):
    """quote is a nonempty excerpt of text: exactly, or under normalization when loose."""
    if not quote.strip():
        return False
    if quote in text:
        return True
    return loose and bool(normalized(quote).strip(EDGES)) and normalized(quote).strip(EDGES) in normalized(text)
