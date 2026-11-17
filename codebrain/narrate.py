"""AI narrative: feed the structural brain to an LLM and get a plain-English
explanation - a senior engineer walking the project's owner through their code.

Two providers, chosen automatically:
  - OpenRouter  (if OPENROUTER_API_KEY is set) - OpenAI-compatible, stdlib only.
  - Anthropic   (if the `anthropic` package + credentials are available).

Degrades gracefully: if neither is available, raise NarrateUnavailable and let
the CLI fall back to the offline structural tour.
"""

import json
import os
import urllib.error
import urllib.request

from . import find as find_mod
from .render import _external_deps

ANTHROPIC_MODEL = "claude-opus-4-8"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_OPENROUTER_MODEL = "poolside/laguna-m.1:free"


class NarrateUnavailable(Exception):
    """Raised when no AI provider can run (no key / no package / no network)."""


# ----------------------------------------------------------------------------
# .env support (so a beginner can drop OPENROUTER_API_KEY in a file)
# ----------------------------------------------------------------------------
def load_dotenv(start):
    """Load KEY=VALUE lines from a .env near `start` into os.environ (no overwrite)."""
    here = os.path.abspath(start)
    for folder in (here, os.path.dirname(os.path.abspath(__file__)),
                   os.path.dirname(os.path.dirname(os.path.abspath(__file__)))):
        path = os.path.join(folder, ".env")
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    key, val = key.strip(), val.strip().strip('"').strip("'")
                    os.environ.setdefault(key, val)
        except OSError:
            pass


# ----------------------------------------------------------------------------
# Compact, deterministic summary of the brain
# ----------------------------------------------------------------------------
def build_summary(project):
    lines = [f"PROJECT: {project.name}", "\nTECH STACK:"]
    if project.stack:
        for desc, manifest in project.stack:
            lines.append(f"  - {desc} (from {manifest})")
    else:
        lines.append("  - unknown (no manifest found)")

    lines.append("\nENTRY POINTS:")
    for f in project.entry_points[:8]:
        lines.append(f"  - {f.rel}")

    lines.append("\nFILES (path | classes | functions | external deps):")
    for f in project.files:
        classes = ",".join(f.classes) if f.classes else "-"
        funcs = ",".join(fn.replace(" (async)", "") for fn in f.funcs) if f.funcs else "-"
        deps = ",".join(_external_deps(f)[:8]) if _external_deps(f) else "-"
        doc = f"  # {f.doc}" if f.doc else ""
        lines.append(f"  {f.rel} | {classes} | {funcs} | {deps}{doc}")

    lines.append("\nIMPORT GRAPH (file -> connects to):")
    for rel in sorted(project.import_graph):
        targets = sorted(project.import_graph[rel])
        if targets:
            lines.append(f"  {rel} -> {', '.join(targets)}")

    return "\n".join(lines)


SYSTEM_INTRO = (
    "You are a senior software engineer with 20 years of experience, sitting next "
    "to the owner of this codebase. Many of them are beginners who built the project "
    "quickly with AI tools and have lost track of how it fits together. Explain their "
    "OWN project to them in plain, friendly English - no jargon without a quick "
    "definition. Be concrete and specific to THIS project (real file and function "
    "names), never generic. Below is a structural map of the whole repository; ground "
    "everything you say in it and do not invent files or behavior that isn't there.\n\n"
    "===== PROJECT MAP =====\n"
)


# ----------------------------------------------------------------------------
# Providers
# ----------------------------------------------------------------------------
def _openrouter_stream(system_text, user_text, on_piece):
    key = os.environ["OPENROUTER_API_KEY"]
    model = os.environ.get("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL)
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_text},
        ],
        "stream": True,
    }).encode("utf-8")

    req = urllib.request.Request(
        OPENROUTER_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "X-Title": "codebrain",
        },
        method="POST",
    )
    collected = []
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            for raw in resp:
                line = raw.decode("utf-8", errors="ignore").strip()
                if not line or line.startswith(":"):   # comments/heartbeats
                    continue
                if not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                piece = delta.get("content")
                if piece:
                    collected.append(piece)
                    if on_piece:
                        on_piece(piece)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="ignore")[:300]
        if e.code in (401, 403):
            raise NarrateUnavailable(
                f"OpenRouter rejected the key ({e.code}). Check OPENROUTER_API_KEY."
            )
        raise NarrateUnavailable(f"OpenRouter error {e.code}: {detail}")
    except urllib.error.URLError as e:
        raise NarrateUnavailable(f"couldn't reach OpenRouter ({e.reason}).")
    return "".join(collected)


def _anthropic_stream(system_text, user_text, on_piece):
    try:
        import anthropic
    except ImportError:
        raise NarrateUnavailable(
            "no AI provider available. Set OPENROUTER_API_KEY, or "
            "`pip install anthropic` + set ANTHROPIC_API_KEY."
        )
    client = anthropic.Anthropic()
    system_blocks = [{
        "type": "text",
        "text": system_text,
        "cache_control": {"type": "ephemeral"},
    }]
    collected = []
    try:
        with client.messages.stream(
            model=ANTHROPIC_MODEL,
            max_tokens=64000,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            system=system_blocks,
            messages=[{"role": "user", "content": user_text}],
        ) as stream:
            for text in stream.text_stream:
                collected.append(text)
                if on_piece:
                    on_piece(text)
    except anthropic.AuthenticationError:
        raise NarrateUnavailable(
            "no Anthropic credentials. Set ANTHROPIC_API_KEY or run `ant auth login`."
        )
    except TypeError as e:
        if "authentication" in str(e).lower():
            raise NarrateUnavailable(
                "no Anthropic credentials. Set ANTHROPIC_API_KEY or run `ant auth login`."
            )
        raise
    except anthropic.APIConnectionError:
        raise NarrateUnavailable("couldn't reach the Anthropic API (check your connection).")
    return "".join(collected)


def _run(project, system_text, user_text, on_piece=None):
    load_dotenv(project.root)
    if os.environ.get("OPENROUTER_API_KEY"):
        return _openrouter_stream(system_text, user_text, on_piece)
    return _anthropic_stream(system_text, user_text, on_piece)


# ----------------------------------------------------------------------------
# Public entry points
# ----------------------------------------------------------------------------
def narrate_tour(project, on_piece=None):
    """Return a plain-English tour of the whole project. May raise NarrateUnavailable."""
    system_text = SYSTEM_INTRO + build_summary(project)
    user_text = (
        "Give me a friendly walkthrough of my project. Cover, in order:\n"
        "1. In one or two sentences, what this app is.\n"
        "2. What each main folder is for.\n"
        "3. Where the app starts and what happens first when it runs.\n"
        "4. How the big pieces connect (frontend to backend, data flow).\n"
        "Keep it tight and readable - short paragraphs and small lists."
    )
    return _run(project, system_text, user_text, on_piece)


def narrate_find(project, slice_, on_piece=None):
    """Return an AI explanation of a located slice + where the likely cause is."""
    system_text = SYSTEM_INTRO + build_summary(project)
    pack = find_mod.context_pack(slice_, max_bytes=90_000)
    user_text = (
        f'My problem: "{slice_.query}"\n\n'
        "codebrain located the files below as the ones that matter. Using their "
        "actual source, explain in plain English:\n"
        "1. Which file/function does what in this flow.\n"
        "2. The single most likely place the problem is coming from, and why.\n"
        "3. A concrete thing to check or change first.\n\n"
        + pack
    )
    return _run(project, system_text, user_text, on_piece)


def narrate_chat(project, question, on_piece=None):
    """Answer any question about the project - the engine behind the chat panel.

    Always grounds on the structural map; when the question points at specific
    files, pulls in their real source too so the answer is concrete.
    """
    system_text = SYSTEM_INTRO + build_summary(project)
    slice_ = find_mod.find(project, question)
    if slice_.hits:
        pack = find_mod.context_pack(slice_, max_bytes=80_000)
        user_text = (
            f"My question: {question}\n\n"
            "Here are the files from my project that look most relevant:\n\n"
            + pack
            + "\n\nAnswer my question clearly and specifically for THIS project. "
            "If it's a bug, name the likely cause and a concrete fix. If it's "
            "'how does X work', explain the flow across these files. Keep it "
            "readable - short paragraphs, small lists, real file/function names."
        )
    else:
        user_text = (
            f"My question: {question}\n\n"
            "Answer using the project map above. Be specific to THIS project and "
            "keep it readable."
        )
    return _run(project, system_text, user_text, on_piece)
