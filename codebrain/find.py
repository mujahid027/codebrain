"""Find-what-matters: given a problem in plain English, return the exact files
and functions that matter - then hand back their source as a paste-ready
"context pack" for any AI.

Pure structure: keyword-seed the query, then expand along the import graph so
you get the *connected web* of files, not isolated keyword hits.
"""

import os
import re
from dataclasses import dataclass, field

# Words that carry no signal for locating code.
STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were", "be",
    "to", "of", "in", "on", "at", "it", "its", "my", "me", "i", "you", "your",
    "this", "that", "these", "those", "for", "with", "as", "so", "if", "then",
    "again", "back", "when", "why", "how", "what", "which", "not", "no", "do",
    "does", "did", "can", "cannot", "cant", "wont", "will", "should", "would",
    "keeps", "keep", "still", "just", "get", "gets", "getting", "let", "lets",
    "page",  # too generic on its own; folder hint handles real "pages/"
}

# A few plain-English -> code synonyms so "login" finds auth/session code, etc.
SYNONYMS = {
    "login": ["auth", "signin", "session", "token", "credential"],
    "logout": ["auth", "session"],
    "signin": ["auth", "login", "session"],
    "signup": ["register", "auth"],
    "register": ["signup", "auth"],
    "password": ["auth", "reset", "credential"],
    "authorize": ["auth", "permission", "role"],
    "authorization": ["auth", "permission", "middleware"],
    "permission": ["auth", "role", "middleware"],
    "redirect": ["route", "router", "navigate"],
    "route": ["router", "routing", "navigate"],
    "cart": ["basket", "order"],
    "checkout": ["order", "payment", "cart"],
    "payment": ["checkout", "order", "stripe"],
    "image": ["upload", "media", "photo", "picture"],
    "upload": ["image", "file", "media"],
    "cache": ["redis", "cached"],
    "database": ["db", "sql", "model", "orm"],
    "profile": ["account", "user"],
    "email": ["mail", "smtp"],
    "search": ["query", "filter"],
}

_SPLIT = re.compile(r"[^a-zA-Z0-9]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def tokenize(text):
    """Lowercase word tokens, splitting camelCase and snake_case."""
    words = []
    for chunk in _SPLIT.split(text or ""):
        if not chunk:
            continue
        for piece in _CAMEL.split(chunk):
            piece = piece.lower()
            if len(piece) >= 2:
                words.append(piece)
    return words


def query_terms(query):
    """Meaningful query tokens, expanded with synonyms."""
    terms = set()
    for t in tokenize(query):
        if t in STOPWORDS or len(t) < 3:
            continue
        terms.add(t)
        for syn in SYNONYMS.get(t, []):
            terms.add(syn)
    return terms


@dataclass
class Hit:
    file: object          # FileInfo
    score: float
    reasons: list = field(default_factory=list)
    connected: bool = False   # pulled in via the import graph, not a direct match


@dataclass
class Slice:
    query: str
    hits: list = field(default_factory=list)   # ranked list[Hit]


def _score_file(fileinfo, terms):
    """How strongly a file matches the query terms, with human reasons."""
    score = 0.0
    reasons = []

    name = os.path.basename(fileinfo.rel)
    name_tokens = set(tokenize(name))
    hit_name = name_tokens & terms
    if hit_name:
        score += 5 * len(hit_name)
        reasons.append(f"file name matches {', '.join(sorted(hit_name))}")

    folder_tokens = set(tokenize(os.path.dirname(fileinfo.rel)))
    hit_folder = folder_tokens & terms
    if hit_folder:
        score += 3 * len(hit_folder)
        reasons.append(f"in a folder about {', '.join(sorted(hit_folder))}")

    fn_hits = set()
    for fn in fileinfo.funcs:
        fn_hits |= set(tokenize(fn)) & terms
    if fn_hits:
        score += 3 * len(fn_hits)
        reasons.append(f"has functions about {', '.join(sorted(fn_hits))}")

    cls_hits = set()
    for c in fileinfo.classes:
        cls_hits |= set(tokenize(c)) & terms
    if cls_hits:
        score += 2 * len(cls_hits)
        reasons.append(f"defines classes about {', '.join(sorted(cls_hits))}")

    if fileinfo.doc:
        doc_hits = set(tokenize(fileinfo.doc)) & terms
        if doc_hits:
            score += 2 * len(doc_hits)
            reasons.append(f"described as {', '.join(sorted(doc_hits))}")

    # Tests exercise the code but rarely contain the bug - keep them, rank lower.
    low = fileinfo.rel.lower()
    if score > 0 and ("test" in name.lower() or "/test" in low or low.startswith("test")):
        score *= 0.4
        reasons.append("(a test file)")

    return score, reasons


def find(project, query, max_files=12):
    """Locate the files that matter for `query`."""
    terms = query_terms(query)
    by_rel = project.by_rel()

    # 1. Seed: score every file, keep the ones that matched.
    seeds = {}
    for f in project.files:
        score, reasons = _score_file(f, terms)
        if score > 0:
            seeds[f.rel] = Hit(file=f, score=score, reasons=reasons)

    # 2. Expand: pull in files directly connected to a seed (import graph).
    for rel in list(seeds):
        for neighbor in project.import_graph.get(rel, ()):
            if neighbor in seeds:
                seeds[neighbor].score += 1  # reinforced by a real connection
            elif neighbor in by_rel:
                seeds[neighbor] = Hit(
                    file=by_rel[neighbor],
                    score=1.5,
                    reasons=[f"connected to {os.path.basename(rel)}"],
                    connected=True,
                )

    ranked = sorted(seeds.values(), key=lambda h: (-h.score, h.file.rel))
    return Slice(query=query, hits=ranked[:max_files])


# ----------------------------------------------------------------------------
# Output
# ----------------------------------------------------------------------------
def render_slice(slice_):
    out = []
    w = out.append
    w("=" * 70)
    w(f"  FILES THAT MATTER FOR:  {slice_.query}")
    w("=" * 70)
    if not slice_.hits:
        w("\n  No matching files. Try different words (e.g. a function or feature name).")
        return "\n".join(out)

    w("\n  Start with these (most relevant first):\n")
    for h in slice_.hits:
        tag = "  ~ " if h.connected else "  * "
        w(f"{tag}{h.file.rel}")
        if h.reasons:
            w(f"        why: {'; '.join(h.reasons)}")
        if h.file.funcs:
            names = ", ".join(h.file.funcs[:6])
            w(f"        functions: {names}")
    w("\n  ( * = direct match,  ~ = connected to a match )")
    w("\n  Tip: run again with --save pack.txt to get the full source of these")
    w("  files as one context pack you can paste into any AI.")
    return "\n".join(out)


def context_pack(slice_, max_bytes=120_000):
    """Concatenate the source of the matched files, ready to paste into any AI."""
    parts = []
    parts.append(
        "# Context pack for: " + slice_.query + "\n"
        "# These are the files that matter for this problem, gathered by codebrain.\n"
        "# Paste this whole block into any AI and ask it to help.\n"
    )
    total = 0
    for h in slice_.hits:
        try:
            with open(h.file.abs, "r", encoding="utf-8", errors="ignore") as fh:
                src = fh.read()
        except OSError:
            continue
        header = f"\n\n===== FILE: {h.file.rel} =====\n"
        chunk = header + src
        if total + len(chunk) > max_bytes:
            parts.append(header + "// (omitted - context pack size limit reached)\n")
            break
        parts.append(chunk)
        total += len(chunk)
    return "".join(parts)
