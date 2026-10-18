"""The logger tree — every module logs under `atlas.<layer>`, and a layer's
level can actually be set.

Before 2026-08-25 this was 18 modules on a flat `"atlas"` and 9 on ad-hoc
dotted children (`atlas.auth_config` was a SIBLING of `atlas.auth`, not a
child), so there was no way to ask for "the dataset layer, louder" — the one
global ATLAS_LOG_LEVEL moved all 28 at once. This test is the tripwire for a
new module quietly rejoining the flat name.
"""

import logging
import os
import re
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The layers app.py documents. A new layer is a deliberate act: add it here.
LAYERS = {"web", "api", "auth", "data", "io", "live"}

# Names that are cross-cutting rather than layer members.
ALLOWED_EXACT = {"atlas.settings"}

_GETLOGGER = re.compile(r'getLogger\(\s*"([^"]*)"\s*\)')


def _module_files():
    skip = {"tests", "__pycache__", ".pytest-tmp", ".pytest_cache", "migrations"}
    for root, dirs, files in os.walk(HERE):
        dirs[:] = [d for d in dirs if d not in skip and not d.startswith(".")]
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(root, f)


def _declared_logger_names():
    found = {}
    for path in _module_files():
        with open(path, encoding="utf-8") as fh:
            for name in _GETLOGGER.findall(fh.read()):
                found.setdefault(name, []).append(os.path.relpath(path, HERE))
    return found


def test_every_logger_is_in_the_tree():
    bad = {}
    for name, files in _declared_logger_names().items():
        if name in ALLOWED_EXACT:
            continue
        parts = name.split(".")
        if len(parts) < 2 or parts[0] != "atlas" or parts[1] not in LAYERS:
            bad[name] = files
    assert not bad, (
        "loggers outside the atlas.<layer> tree (see the map in app.py): "
        f"{bad}. A flat 'atlas' means this module cannot be tuned with its layer."
    )


def test_no_module_uses_the_flat_atlas_logger():
    """The specific regression: `logging.getLogger("atlas")` in a module."""
    names = _declared_logger_names()
    assert "atlas" not in names, (
        f"these modules are back on the flat logger: {names.get('atlas')}")


def test_the_layers_are_all_populated():
    """A layer nothing logs to is a layer that should not be in the map."""
    used = set()
    for name in _declared_logger_names():
        parts = name.split(".")
        if len(parts) >= 2 and parts[0] == "atlas":
            used.add(parts[1])
    assert LAYERS <= used, f"documented but unused layers: {LAYERS - used}"


# ── The knob ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,levels,rejected", [
    ("", {}, []),
    ("atlas.data=DEBUG", {"atlas.data": "DEBUG"}, []),
    ("  atlas.io = warning , atlas.auth=ERROR ",
     {"atlas.io": "WARNING", "atlas.auth": "ERROR"}, []),
    ("atlas.data=NOPE", {}, ["atlas.data=NOPE"]),
    ("=DEBUG", {}, ["=DEBUG"]),
    # a real logging attribute that is not an int must not sneak through and
    # reach setLevel as a function
    ("atlas.data=getLogger", {}, ["atlas.data=getLogger"]),
    # one bad entry must not discard the good ones beside it
    ("atlas.io=DEBUG,atlas.data=NOPE",
     {"atlas.io": "DEBUG"}, ["atlas.data=NOPE"]),
])
def test_log_levels_parsing(raw, levels, rejected):
    import settings
    assert settings._parse_log_levels(raw) == (levels, rejected)


def test_a_rejected_entry_is_reported_not_swallowed():
    """app.py logs what it could not use; the parse must hand it something to
    report. A logging knob that silently does nothing is the worst arm."""
    import settings
    _, rejected = settings._parse_log_levels("atlas.data=LOUDER")
    assert rejected == ["atlas.data=LOUDER"]


def test_a_layer_level_actually_reaches_its_children():
    """Not a test of logging itself — a test that the NAMES nest, which is the
    whole point of the rename. Setting `atlas.data` must reach labdata."""
    data, live = logging.getLogger("atlas.data"), logging.getLogger("atlas.live")
    child = logging.getLogger("atlas.data.labdata")
    sibling = logging.getLogger("atlas.live.signals")
    data.setLevel(logging.ERROR)
    live.setLevel(logging.DEBUG)
    try:
        assert child.getEffectiveLevel() == logging.ERROR      # inherited the layer
        assert not child.isEnabledFor(logging.INFO)
        # ...and the neighbouring layer is untouched by it
        assert sibling.getEffectiveLevel() == logging.DEBUG
    finally:
        data.setLevel(logging.NOTSET)
        live.setLevel(logging.NOTSET)


def test_the_log_format_prints_the_logger_name():
    """A tree is worthless in a line that hard-codes the literal `atlas`."""
    with open(os.path.join(HERE, "app.py"), encoding="utf-8") as fh:
        src = fh.read()
    fmt = re.search(r'format="([^"]*)"', src)
    assert fmt, "no logging format in app.py"
    assert "%(name)s" in fmt.group(1), fmt.group(1)
