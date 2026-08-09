"""Guard against @st.cache_data functions whose cache key is empty.

st.cache_data deliberately EXCLUDES underscore-prefixed arguments from the hash — that is
the documented escape hatch for passing an unhashable value like a live sqlite3.Connection
(streamlit/runtime/caching/cache_utils.py: `if arg_name is not None and
arg_name.startswith("_"): continue`).

The trap: a cache-BUSTER passed as `_mtime` is silently ignored too. A function whose
arguments are ALL underscore-prefixed has an EMPTY cache key, so the first result computed
on a warm container is served forever — the DB can be rebuilt, the seed CSV re-edited, the
render code changed, and the page never updates. Seven functions in streamlit_app.py were
written this way, which is why editing data/seed/aip_commission.csv appeared to do nothing
and why the app kept seeming to need a reboot.

This test parses the module rather than importing it (importing would need a live DB).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
MODULES = [REPO / "streamlit_app.py", REPO / "lrp_page.py"]
MODULES += sorted((REPO / "src").glob("*page*.py"))


def _is_cache_data(dec: ast.expr) -> bool:
    """Match @st.cache_data and @st.cache_data(...) — but NOT cache_resource, whose
    whole purpose is to memoize one shared object (a connection) for the process."""
    node = dec.func if isinstance(dec, ast.Call) else dec
    return isinstance(node, ast.Attribute) and node.attr == "cache_data"


def _cached_funcs():
    for path in MODULES:
        if not path.exists():
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if any(_is_cache_data(d) for d in node.decorator_list):
                    args = [a.arg for a in
                            node.args.posonlyargs + node.args.args + node.args.kwonlyargs]
                    yield path.name, node.name, node.lineno, args


def test_there_are_cached_functions_to_check():
    """Fail loudly if the AST walk silently matches nothing."""
    assert list(_cached_funcs()), "no @st.cache_data functions found — is the matcher broken?"


@pytest.mark.parametrize("mod,func,lineno,args",
                         list(_cached_funcs()),
                         ids=lambda v: str(v) if isinstance(v, str) else "")
def test_cache_key_is_not_empty(mod, func, lineno, args):
    """A cached function with arguments must have at least one that is actually hashed."""
    if not args:
        return  # zero-arg: a constant for the process's life, and that is intended
    hashed = [a for a in args if not a.startswith("_")]
    assert hashed, (
        f"{mod}:{lineno} {func}({', '.join(args)}) — every argument is underscore-prefixed, "
        f"so st.cache_data hashes NOTHING and the first result is cached forever. "
        f"Drop the underscore from the cache-buster(s); keep it only on unhashable args "
        f"such as a sqlite3.Connection."
    )
