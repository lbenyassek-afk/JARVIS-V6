from __future__ import annotations

import re
import unicodedata


_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "for", "from", "how", "i", "in", "is", "it",
    "my", "of", "on", "or", "that", "the", "this", "to", "was", "what", "when", "where", "with",
    "un", "une", "des", "du", "de", "et", "est", "la", "le", "les", "pour", "que", "qui",
    "el", "la", "los", "las", "de", "del", "y", "para", "que", "una", "uno",
    "der", "die", "das", "und", "ein", "eine", "mit", "für", "ist",
    "il", "lo", "gli", "le", "di", "e", "per", "che", "una",
    "o", "a", "os", "as", "do", "da", "e", "para", "que", "uma",
    "في", "من", "إلى", "على", "عن", "ما", "ماذا", "هذا", "هذه", "هو", "هي", "و",
}


def normalize(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = "".join(char for char in unicodedata.normalize("NFKD", text)
                   if not unicodedata.combining(char))
    return " ".join(re.findall(r"[^\W_]+", text, flags=re.UNICODE))


def terms(value: str, minimum: int = 2) -> set[str]:
    return {word for word in normalize(value).split()
            if len(word) >= minimum and word not in _STOP_WORDS}


def relevance(query: str, candidate: str) -> int:
    query_normal = normalize(query)
    if not query_normal:
        return 1
    candidate_normal = normalize(candidate)
    query_terms = terms(query_normal)
    candidate_terms = terms(candidate_normal)
    overlap = query_terms & candidate_terms
    score = sum(3 + min(len(word), 10) for word in overlap)
    if query_normal and query_normal in candidate_normal:
        score += 18
    # Partial matching helps related forms across French, Spanish and English.
    for word in query_terms - overlap:
        if len(word) >= 5 and any(item.startswith(word[:5]) or word.startswith(item[:5])
                                  for item in candidate_terms if len(item) >= 5):
            score += 2
    return score
