#!/usr/bin/env python3
"""
explain.py  -  Understand any codebase.

Point it at a repo and it explains, in plain English, what everything does and
how it connects. When you have a bug, it can also hand you the exact files that
matter as a paste-ready context pack for any AI.

    python explain.py <repo>                      structural tour (no AI, offline)
    python explain.py <repo> --save [path]        write the tour to Markdown
    python explain.py <repo> --find "<problem>"   exact files/functions that matter
    python explain.py <repo> --find "<problem>" --save pack.txt
    python explain.py <repo> --narrate            AI explanation, opened in your browser
    python explain.py <repo> --find "<problem>" --narrate   AI-explained slice

Structure and search work with no AI and no internet. --narrate calls an LLM
(OpenRouter if OPENROUTER_API_KEY is set, else Anthropic) and opens a clean,
formatted page in your browser. Without a key it falls back to the offline tour.
"""

import argparse
import os
import sys
import tempfile
import webbrowser

# Print UTF-8 even on Windows consoles (models emit em-dashes, smart quotes, etc.)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from codebrain import find as find_mod
from codebrain import narrate as narrate_mod
from codebrain import render
from codebrain.scan import build_project


def _default_tour_path(project):
    return os.path.join(project.root, "PROJECT_TOUR.md")


def _progress(_piece, _state={"n": 0}):
    """Show a lightweight 'working...' dotted line while the AI streams."""
    _state["n"] += 1
    if _state["n"] % 3 == 0:
        sys.stdout.write(".")
        sys.stdout.flush()


def _open_in_browser(title, subtitle, markdown_text):
    """Render the AI answer as a clean HTML page and open it in the browser."""
    page = render.render_report_html(title, markdown_text, subtitle=subtitle)
    fd, path = tempfile.mkstemp(prefix="codebrain_", suffix=".html")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(page)
    webbrowser.open("file://" + os.path.abspath(path))
    print(f"\n  Opened your explanation in the browser.\n  (saved at: {path})")


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="explain.py",
        description="Understand any codebase in plain English.",
    )
    parser.add_argument("repo", nargs="?", default=".",
                        help="path to the repo (default: current folder)")
    parser.add_argument("--find", metavar="PROBLEM",
                        help="describe a bug/feature; get the exact files that matter")
    parser.add_argument("--save", nargs="?", const="", metavar="PATH",
                        help="save output to a file (Markdown tour, or context pack with --find)")
    parser.add_argument("--narrate", action="store_true",
                        help="AI explanation, opened as a clean page in your browser")
    args = parser.parse_args(argv)

    if not os.path.isdir(args.repo):
        print(f"! Not a folder: {args.repo}")
        return 1

    project = build_project(args.repo)

    # --- Find-what-matters ---
    if args.find:
        slice_ = find_mod.find(project, args.find)

        if args.save is not None:
            path = args.save or os.path.join(os.getcwd(), "context_pack.txt")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(find_mod.context_pack(slice_))
            print(find_mod.render_slice(slice_))
            print(f"\n  Context pack written to: {path}")
        else:
            print(find_mod.render_slice(slice_))

        if args.narrate:
            print("\n  Asking the AI to explain these files", end="")
            try:
                text = narrate_mod.narrate_find(project, slice_, on_piece=_progress)
                _open_in_browser(f"Fixing: {slice_.query}", "AI diagnosis", text)
            except narrate_mod.NarrateUnavailable as e:
                print(f"\n  (AI unavailable - {e})")
        return 0

    # --- Save the tour to Markdown ---
    if args.save is not None:
        path = args.save or _default_tour_path(project)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(render.render_markdown(project))
        print(f"Project tour written to: {path}")
        return 0

    # --- AI narrative tour (opens in browser) ---
    if args.narrate:
        print(f"  Reading {project.name} and writing a plain-English tour", end="")
        try:
            text = narrate_mod.narrate_tour(project, on_piece=_progress)
            _open_in_browser(f"{project.name} - explained", "AI walkthrough", text)
            return 0
        except narrate_mod.NarrateUnavailable as e:
            print(f"\n(AI unavailable - {e})")
            print("Showing the offline structural tour instead:\n")
            # fall through to the structural tour

    # --- Default: structural terminal tour ---
    print(render.render_terminal(project))
    return 0


if __name__ == "__main__":
    sys.exit(main())
