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


# hiragana, katakana, CJK ideographs
_JAPANESE = re.compile(r"[぀-ヿ一-鿿]")


def japanese_ratio(text: str) -> float:
    """Share of non-space characters that are Japanese."""
    letters = [c for c in text if not c.isspace()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if _JAPANESE.match(c)) / len(letters)


def language_shift(old: str, new: str) -> str:
    """Classify a change as a rewrite or a language swap.

    An EN story asset does not always contain English. An event can ship with the
    Japanese script still in place and receive its English localisation a release or
    two later, and that shows up in the diff exactly like a rewording — 71% of the
    changed lines found across the whole catalogue are this, not editing. Presenting
    "What is this place?!" -> "なんだここは～～～～！！！！" as a retranslation would be
    a plain misreading of the data.

    Returns ``rewrite`` (both sides English), ``localised`` (JP -> EN, the first English
    text arriving), ``untranslated`` (EN -> JP, a regression) or ``japanese`` (both
    sides Japanese).
    """
    old_jp, new_jp = japanese_ratio(old) > 0.5, japanese_ratio(new) > 0.5
    if old_jp and new_jp:
        return "japanese"
    if old_jp:
        return "localised"
    if new_jp:
        return "untranslated"
    return "rewrite"
