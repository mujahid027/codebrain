#!/usr/bin/env python3
"""Bridge between the VS Code chat panel and the Python brain.

The extension runs:  python chat_bridge.py <repo> "<question>"
and reads the answer from stdout as it streams. All the real work is in the
`codebrain` package - this is just the doorway.
"""

import os
import sys

# Make sure we can import the codebrain package next to this file.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Stream UTF-8 so the panel gets clean text on Windows too.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from codebrain import narrate as narrate_mod
from codebrain.scan import build_project


def main():
    if len(sys.argv) < 3:
        sys.stdout.write("Usage: chat_bridge.py <repo> <question>")
        return 1

    repo, question = sys.argv[1], sys.argv[2]
    if not os.path.isdir(repo):
        sys.stdout.write(f"Can't find that project folder: {repo}")
        return 1

    project = build_project(repo)

    def emit(piece):
        sys.stdout.write(piece)
        sys.stdout.flush()

    try:
        narrate_mod.narrate_chat(project, question, on_piece=emit)
    except narrate_mod.NarrateUnavailable as e:
        sys.stdout.write(f"\n\n_(AI unavailable - {e})_")
    return 0


if __name__ == "__main__":
    sys.exit(main())
