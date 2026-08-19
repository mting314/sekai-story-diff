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


def _letters(text: str) -> list[str]:
    """Characters that carry language: alphanumerics and Japanese script.

    Deliberately excludes punctuation and symbols. Sekai dialogue is dense with ellipsis
    and dashes, and counting those as evidence of "not Japanese" is what made the old
    ratio wrong.
    """
    return [c for c in text if c.isalnum() or _JAPANESE.match(c)]


def japanese_ratio(text: str) -> float:
    """Share of *language-carrying* characters that are Japanese.

    Measured over letters rather than all non-space characters. ``'ん…………'`` is one kana
    among five ellipsis marks: by character it reads 0.17 and looks English, by letter it
    reads 1.0 and is plainly Japanese.
    """
    letters = _letters(text)
    if not letters:
        return 0.0
    return sum(1 for c in letters if _JAPANESE.match(c)) / len(letters)


def language_shift(old: str, new: str) -> str:
    """Classify a change as an edit, a language swap, or typography.

    An EN story asset does not always contain English. An event can ship with the
    Japanese script still in place and receive its English localisation a release or
    two later, and that shows up in the diff exactly like a rewording. Presenting
    "What is this place?!" -> "なんだここは～～～～！！！！" as a retranslation would be
    a plain misreading of the data.

    Returns:
      ``rewrite``       both sides English — the only class the site treats as editing
      ``localised``     JP -> EN, the first English text arriving
      ``untranslated``  EN -> JP, a regression
      ``japanese``      both sides Japanese
      ``punctuation``   no letters either side, e.g. '…………' -> '...' — typography from
                        the localisation pass, not an edit
    """
    old_letters, new_letters = _letters(old), _letters(new)
    if not old_letters and not new_letters:
        return "punctuation"

    # A ratio alone still misses lines where a Latin proper noun dilutes the Japanese:
    #   '——どうも。あれ、Leo/needだ' -> "Hello. Oh, Leo/need's also here."
    # 'Leo/need' is enough Latin to drag it under any sensible threshold. Kana or kanji
    # on the old side with none on the new is decisive on its own — English story text
    # never carries Japanese script, verified across every line in the corpus.
    old_has, new_has = bool(_JAPANESE.search(old)), bool(_JAPANESE.search(new))
    if old_has and not new_has:
        return "localised"
    if new_has and not old_has:
        return "untranslated"

    old_jp, new_jp = japanese_ratio(old) > 0.5, japanese_ratio(new) > 0.5
    if old_jp and new_jp:
        return "japanese"
    if old_jp:
        return "localised"
    if new_jp:
        return "untranslated"
    return "rewrite"
