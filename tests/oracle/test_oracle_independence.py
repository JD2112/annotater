"""
Independence guard (Task F, section 2): the oracle module must not import
anything from the production package, nor any library that implements
interval logic. Enforced structurally, by parsing the module's imports.
"""

from __future__ import annotations

import ast
from pathlib import Path

import tests.oracle.reference as reference

FORBIDDEN_ROOTS = {
    "streamlit_app", "tests", "pandas", "polars", "polars_bio", "pybedtools",
    "numpy", "intervaltree", "pyranges", "bioframe",
}


def test_reference_imports_nothing_from_production_or_interval_libraries():
    tree = ast.parse(Path(reference.__file__).read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import would reach sibling test modules
                imported.add("<relative>")
            elif node.module:
                imported.add(node.module.split(".")[0])
    imported.discard("__future__")
    assert imported.isdisjoint(FORBIDDEN_ROOTS | {"<relative>"}), imported
