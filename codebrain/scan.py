"""The brain: read a repo structurally and build a reusable model of it.

Produces a `Project` object holding the folder guide, tech stack, entry points,
per-file details (functions / classes / imports), and an *import graph* — which
file connects to which. Everything else (tour, find, narrate) reads this model
instead of re-reading the repo.

No AI, no internet. Python `ast` for .py; regex for JS/TS-family files.
"""

import ast
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field

# ----------------------------------------------------------------------------
# What to ignore. These folders are noise, not "your project".
# ----------------------------------------------------------------------------
IGNORE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env",
    "dist", "build", ".next", ".nuxt", "out", "coverage", ".idea",
    ".vscode", ".pytest_cache", ".mypy_cache", "target", "vendor",
    ".cache", "tmp", ".turbo", "bin", "obj",
}
IGNORE_FILES = {".DS_Store"}

CODE_EXTS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".go", ".rb", ".php", ".java", ".vue", ".svelte",
}
JS_EXTS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte"}
# Extensions tried when resolving a JS/TS import that omits its extension.
JS_RESOLVE_EXTS = [".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte"]

# ----------------------------------------------------------------------------
# Heuristics: what a folder is *probably* for, judging by its name.
# ----------------------------------------------------------------------------
FOLDER_HINTS = {
    "src": "the main source code of your app",
    "app": "the main application code (often routes/pages)",
    "pages": "individual pages of your site (usually one file = one route/URL)",
    "routes": "URL routing - which address shows which page/handler",
    "components": "reusable UI building blocks (buttons, cards, forms)",
    "public": "static files served as-is (images, fonts, favicon)",
    "static": "static files served as-is (images, css, js)",
    "assets": "images, fonts and other media used by the app",
    "images": "image files used in the site",
    "img": "image files used in the site",
    "styles": "CSS / styling for how the site looks",
    "css": "CSS / styling for how the site looks",
    "api": "backend endpoints your frontend talks to",
    "controllers": "logic that handles incoming requests",
    "models": "the shape of your data (database tables/objects)",
    "views": "templates that render HTML pages",
    "templates": "HTML templates rendered and sent to the browser",
    "middleware": "code that runs between request and response (e.g. auth checks)",
    "utils": "small helper functions used all over the app",
    "helpers": "small helper functions used all over the app",
    "lib": "shared library code / internal packages",
    "config": "configuration and settings",
    "services": "code that talks to external things (DB, payment, email APIs)",
    "hooks": "reusable stateful logic (React hooks)",
    "store": "global app state (Redux/Vuex/etc.)",
    "context": "shared React state via Context",
    "contexts": "shared React state via Context",
    "tests": "automated tests that check your code works",
    "test": "automated tests that check your code works",
    "__tests__": "automated tests that check your code works",
    "migrations": "database schema changes over time",
    "db": "database setup / connection code",
    "database": "database setup / connection code",
    "auth": "login, signup and permission logic",
    "scripts": "one-off scripts (setup, seeding, tooling)",
    "docs": "documentation",
    "data": "static/seed data used by the app",
    "types": "TypeScript type definitions",
}

ENTRY_HINTS = {
    "main.py", "app.py", "manage.py", "wsgi.py", "asgi.py", "run.py",
    "index.js", "index.ts", "main.js", "main.ts", "server.js", "app.js",
    "index.jsx", "index.tsx", "main.jsx", "main.tsx", "server.ts",
    "index.html", "_app.tsx", "_app.js",
}

STACK_SIGNS = {
    "package.json": "Node.js / JavaScript project",
    "requirements.txt": "Python project (pip dependencies)",
    "pyproject.toml": "Python project (modern packaging)",
    "Pipfile": "Python project (pipenv)",
    "go.mod": "Go project",
    "Cargo.toml": "Rust project",
    "composer.json": "PHP project",
    "Gemfile": "Ruby project",
    "pom.xml": "Java (Maven) project",
    "build.gradle": "Java/Kotlin (Gradle) project",
    "next.config.js": "Next.js (React framework)",
    "next.config.mjs": "Next.js (React framework)",
    "vite.config.js": "Vite build tool",
    "vite.config.ts": "Vite build tool",
    "tailwind.config.js": "Tailwind CSS for styling",
    "Dockerfile": "Dockerized (runs in a container)",
    "docker-compose.yml": "multi-service setup via Docker Compose",
    "manage.py": "Django (Python web framework)",
    "artisan": "Laravel (PHP web framework)",
}


# ----------------------------------------------------------------------------
# The model
# ----------------------------------------------------------------------------
@dataclass
class FileInfo:
    rel: str                      # path relative to repo root (posix separators)
    abs: str                      # absolute path on disk
    lang: str                     # file extension, e.g. ".py"
    lines: int = 0
    funcs: list = field(default_factory=list)
    classes: list = field(default_factory=list)
    imports: list = field(default_factory=list)   # display strings (internal + external)
    doc: str = None               # first line of module docstring, if any


@dataclass
class Project:
    name: str
    root: str
    stack: list = field(default_factory=list)              # human descriptions
    manifests: list = field(default_factory=list)          # manifest filenames found
    files: list = field(default_factory=list)              # list[FileInfo]
    files_by_dir: dict = field(default_factory=dict)        # rel_dir -> [filenames]
    entry_points: list = field(default_factory=list)        # list[FileInfo]
    import_graph: dict = field(default_factory=dict)        # rel -> set(rel) (undirected)

    def by_rel(self):
        return {f.rel: f for f in self.files}


# ----------------------------------------------------------------------------
# Reading a single code file
# ----------------------------------------------------------------------------
def analyze_python(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            src = f.read()
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return None

    funcs, classes, imports = [], [], []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            funcs.append(node.name)
        elif isinstance(node, ast.AsyncFunctionDef):
            funcs.append(node.name + " (async)")
        elif isinstance(node, ast.ClassDef):
            classes.append(node.name)
        elif isinstance(node, ast.Import):
            imports += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)

    docstring = ast.get_docstring(tree)
    return {
        "funcs": funcs,
        "classes": classes,
        "imports": imports,
        "doc": docstring.strip().splitlines()[0] if docstring else None,
        "lines": len(src.splitlines()),
    }


JS_FUNC = re.compile(
    r"(?:function\s+(\w+)|(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(|"
    r"(\w+)\s*\([^)]*\)\s*\{)"
)
JS_CLASS = re.compile(r"class\s+(\w+)")
JS_IMPORT = re.compile(
    r"""(?:import\s.*?from\s+['"]([^'"]+)['"]|require\(\s*['"]([^'"]+)['"]\s*\))"""
)


def analyze_js(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            src = f.read()
    except OSError:
        return None

    funcs = []
    for m in JS_FUNC.finditer(src):
        name = m.group(1) or m.group(2) or m.group(3)
        if name and name not in ("if", "for", "while", "switch", "catch", "function"):
            funcs.append(name)
    classes = JS_CLASS.findall(src)
    imports = [a or b for a, b in JS_IMPORT.findall(src)]

    funcs = list(dict.fromkeys(funcs))
    return {
        "funcs": funcs[:25],
        "classes": classes,
        "imports": list(dict.fromkeys(imports)),
        "doc": None,
        "lines": len(src.splitlines()),
    }


def analyze_file(path):
    ext = os.path.splitext(path)[1]
    if ext == ".py":
        return analyze_python(path)
    if ext in JS_EXTS:
        return analyze_js(path)
    return None


# ----------------------------------------------------------------------------
# Import graph: resolve each file's *internal* imports to other repo files.
# ----------------------------------------------------------------------------
def _posix(p):
    return p.replace("\\", "/")


def _resolve_python(module, rel_paths):
    """Dotted module (e.g. 'app.routes.auth') -> a repo file, by path suffix."""
    frag = module.replace(".", "/")
    candidates = (frag + ".py", frag + "/__init__.py")
    best = None
    for cand in candidates:
        for rp in rel_paths:
            if rp == cand or rp.endswith("/" + cand):
                # prefer the shortest (closest to root) unambiguous match
                if best is None or len(rp) < len(best):
                    best = rp
    return best


def _resolve_js(spec, from_rel, rel_set):
    """Relative specifier (e.g. '../api/auth') -> a repo file."""
    if not spec.startswith("."):
        return None  # bare import = external package
    base = os.path.dirname(from_rel)
    target = _posix(os.path.normpath(os.path.join(base, spec)))
    if target.startswith("../") or target == "..":
        return None
    tries = [target + ext for ext in JS_RESOLVE_EXTS]
    tries += [target + "/index" + ext for ext in JS_RESOLVE_EXTS]
    tries.append(target)  # already had an extension
    for t in tries:
        if t in rel_set:
            return t
    return None


def build_import_graph(files):
    rel_set = {f.rel for f in files}
    rel_paths = list(rel_set)
    graph = defaultdict(set)

    for f in files:
        for imp in f.imports:
            target = None
            if f.lang == ".py":
                target = _resolve_python(imp, rel_paths)
            elif f.lang in JS_EXTS:
                target = _resolve_js(imp, f.rel, rel_set)
            if target and target != f.rel:
                graph[f.rel].add(target)
                graph[target].add(f.rel)  # undirected: "connects to"
    return dict(graph)


# ----------------------------------------------------------------------------
# Walk the repo and assemble the Project.
# ----------------------------------------------------------------------------
def build_project(root):
    root = os.path.abspath(root)
    name = os.path.basename(root.rstrip("/\\"))

    files_by_dir = defaultdict(list)
    files = []
    manifests = []

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        rel_dir = os.path.relpath(dirpath, root)

        for fn in sorted(filenames):
            if fn in IGNORE_FILES:
                continue
            full = os.path.join(dirpath, fn)
            if fn in STACK_SIGNS:
                manifests.append(fn)
            ext = os.path.splitext(fn)[1]
            files_by_dir[rel_dir].append(fn)
            if ext in CODE_EXTS:
                rel = _posix(os.path.relpath(full, root))
                info = FileInfo(rel=rel, abs=full, lang=ext)
                details = analyze_file(full)
                if details:
                    info.lines = details["lines"]
                    info.funcs = details["funcs"]
                    info.classes = details["classes"]
                    info.imports = details["imports"]
                    info.doc = details["doc"]
                files.append(info)

    # tech stack (deduped, order-preserving)
    stack, seen = [], set()
    for m in manifests:
        desc = STACK_SIGNS.get(m)
        if desc and desc not in seen:
            stack.append((desc, m))
            seen.add(desc)

    entry_points = [
        f for f in files
        if os.path.basename(f.rel).lower() in ENTRY_HINTS
    ]

    graph = build_import_graph(files)

    return Project(
        name=name,
        root=root,
        stack=stack,
        manifests=manifests,
        files=sorted(files, key=lambda f: f.rel),
        files_by_dir=dict(files_by_dir),
        entry_points=entry_points,
        import_graph=graph,
    )
