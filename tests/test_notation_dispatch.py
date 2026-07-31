"""
Guards against a method being deleted while calls to it remain.

This is the exact failure that broke the pedagogical note display: commit
841732c removed _draw_enhanced_note and _draw_enhanced_rest but left three call
sites behind. Because "enhanced" is the default notation style, paint() then
raised AttributeError on the first note of every frame and no notehead was ever
drawn — yet the whole suite stayed green, since nothing exercised paint().
"""

import ast
import os

from ui.notation_view import NotationView

MODULE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "src", "ui", "notation_view.py",
)


def _self_called_attributes() -> set[str]:
    """Every name invoked as self.<name>(...) anywhere in notation_view.py."""
    with open(MODULE_PATH, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())

    called = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "self"
        ):
            called.add(func.attr)
    return called


def test_every_dispatched_method_exists():
    called = _self_called_attributes()
    assert called, "AST scan found no self.<method>() calls — the scan is broken"

    missing = sorted(name for name in called if not hasattr(NotationView, name))
    assert not missing, (
        "notation_view.py calls methods that do not exist: "
        + ", ".join(missing)
        + ". A draw method was likely deleted while its call sites remained."
    )


def test_enhanced_draw_methods_present():
    """
    Explicit guard on the two methods whose deletion caused the outage.

    implementation_briefs/phase-2-measure-notation.md:10 lists both under
    'Must survive'; that instruction was not machine-checked, so it was missed.
    """
    for name in ("_draw_enhanced_note", "_draw_enhanced_rest", "_draw_traditional_note"):
        assert hasattr(NotationView, name), f"{name} is missing from NotationView"
