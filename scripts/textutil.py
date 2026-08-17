"""Text normalisation helpers shared by the retranslation diff scripts."""

from __future__ import annotations

import re
import unicodedata

_PUNCT_MAP = {
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "…": "...",
    "—": "-",
    "–": "-",
    " ": " ",
    "〜": "~",
    "～": "~",
    "―": "-",
}


def normalize(text: str) -> str:
    """Fold away formatting-only differences before comparing old vs new lines."""
    text = unicodedata.normalize("NFKC", text)
    for src, dst in _PUNCT_MAP.items():
        text = text.replace(src, dst)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def compare_key(text: str) -> str:
    """Aggressive key for alignment/equality: case- and punctuation-insensitive."""
    text = normalize(text).lower()
    text = re.sub(r"[^a-z0-9 ]+", "", text)
    return re.sub(r"\s+", " ", text).strip()
