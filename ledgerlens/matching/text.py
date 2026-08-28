from __future__ import annotations

import re
from difflib import SequenceMatcher


_TOKEN_RE = re.compile(r"[a-z0-9]+")
_SYNONYMS = {
    "sq": "square",
    "nyc": "new york",
    "ach": "",
    "eft": "",
}
_REFERENCE_STOPWORDS = {"inv", "invoice", "ref", "reference", "payment", "pmt"}


def canonical_text(value: str | None) -> str:
    text = (value or "").lower()
    for token, replacement in _SYNONYMS.items():
        text = re.sub(rf"\b{re.escape(token)}\b", replacement, text)
    return " ".join(_TOKEN_RE.findall(text))


def tokenize(value: str | None) -> list[str]:
    return canonical_text(value).split()


def reference_tokens(reference: str | None) -> set[str]:
    tokens = set(tokenize(reference))
    digits = {token for token in tokens if any(char.isdigit() for char in token)}
    useful = {token for token in tokens if token not in _REFERENCE_STOPWORDS}
    return digits or useful


def reference_key(reference: str | None) -> str:
    return " ".join(sorted(reference_tokens(reference)))


def jaccard_similarity(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 0.0
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def reference_overlap(left_reference: str | None, right_reference: str | None) -> float:
    return round(jaccard_similarity(reference_tokens(left_reference), reference_tokens(right_reference)), 4)


def token_similarity(left: str | None, right: str | None) -> float:
    left_text = canonical_text(left)
    right_text = canonical_text(right)
    if not left_text or not right_text:
        return 0.0

    left_tokens = set(left_text.split())
    right_tokens = set(right_text.split())
    token_score = jaccard_similarity(left_tokens, right_tokens)
    sequence_score = SequenceMatcher(None, left_text, right_text).ratio()
    return round((0.60 * token_score) + (0.40 * sequence_score), 4)
