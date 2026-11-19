"""Which way the imports run: the layers' wall, without moving a file.

The modules under `Web/` are flat, and moving them into packages was weighed
and left (2026-11-12: every import and the deploy and export scripts would
change for a boundary the logger tree already names). What a package would
give is a boundary that fails a build when it is crossed. This is that, as a
test: it reads every module's imports and holds them to the directions that
are true today.

Two kinds of rule:

* **Walls.** True of every module today; a new import that crosses one fails.
* **Known crossings.** Modules that already cross a line a wall would draw.
  Each list is exact: a new crossing fails, and so does a module that has
  stopped crossing but is still listed, so the lists can only get shorter.

Nothing is imported here; the files are parsed. A syntax error in a module is
that module's own tests' business.
"""

import ast
import os
import sys

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Folders under Web/ that hold no application module.
SKIP_DIRS = {"tests", "__pycache__", "static", "templates", "migrations",
             "themes", ".pytest-tmp", ".pytest-tmp-b", ".pytest_cache"}

#: Folders whose modules are engines, senders, importers and the db store:
#: the parts that must run with no web framework and no route beside them.
INNER = ("engines", "senders", "importers", "store")

#: Flat modules that ARE the web layer: Flask is theirs to import.
WEB_LAYER = {"app", "views", "auth_routes", "context", "errors", "security",
             "atlas_auth", "ingest"}

#: Flat modules that import Flask though they are not the web layer. Shrinks only.
KNOWN_FLASK = {"accounts", "api_tokens", "metrics", "redaction", "settings",
               "token_log", "tripwires"}

#: Modules outside `api/` that import a route module. `app` registers the
#: blueprints and `views` serves the page, so those two are the web layer's
#: own; the rest reach into a route module for a helper. Shrinks only.
KNOWN_API = {"alerts", "annalist", "mcp_tools"}

#: The modules a relay box loads from this tree (`relay/atlas_relay.py`):
#: the hub and two importer halves, with nothing beside the standard library,
#: `settings` and `requests` installed.
RELAY_LOADS = ("signals.py", "importers/netbox_client.py", "importers/scan.py")


def _imports(path):
    """(top, nested): the dotted names a module imports at module level, and
    the ones it imports inside a function or a branch."""
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    top, nested = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = ["." * node.level + (node.module or "")]
        else:
            continue
        (top if node in tree.body else nested).update(names)
    return top, nested


def _modules():
    """{path relative to Web/, with forward slashes: (top, nested)}."""
    out = {}
    for folder, dirs, files in os.walk(WEB):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if name.endswith(".py"):
                path = os.path.join(folder, name)
                out[os.path.relpath(path, WEB).replace(os.sep, "/")] = _imports(path)
    return out


MODULES = _modules()


def _root(name):
    return name.split(".")[0]


def _all(rel):
    top, nested = MODULES[rel]
    return top | nested


def _flat(rel):
    return "/" not in rel


def _stem(rel):
    return rel[:-3]


def test_the_tree_was_read():
    """A wrong path would make every rule below pass on nothing."""
    assert len(MODULES) > 100
    for rel in ("app.py", "signals.py", "engines/registry.py", "api/v2/feeds.py"):
        assert rel in MODULES


def test_engines_senders_importers_and_the_store_never_import_flask():
    crossing = sorted(rel for rel in MODULES
                      if rel.split("/")[0] in INNER
                      and any(_root(n) in ("flask", "werkzeug") for n in _all(rel)))
    assert crossing == []


def test_engines_senders_importers_and_the_store_never_import_a_route():
    crossing = sorted(rel for rel in MODULES
                      if rel.split("/")[0] in INNER
                      and any(_root(n) in ("api", "app", "views", "auth_routes")
                              for n in _all(rel)))
    assert crossing == []


def test_only_the_stdio_server_imports_the_app():
    """`app.py` builds the app at import. Anything that imports it starts one."""
    importers = sorted(rel for rel in MODULES if any(_root(n) == "app" for n in _all(rel)))
    assert importers == ["mcp_stdio.py"]


def test_flask_outside_the_web_layer_is_the_known_list_and_no_longer():
    found = {_stem(rel) for rel in MODULES
             if _flat(rel) and any(_root(n) in ("flask", "werkzeug") for n in _all(rel))}
    assert found - WEB_LAYER - KNOWN_FLASK == set(), (
        "a module outside the web layer began importing Flask")
    assert KNOWN_FLASK - found == set(), (
        "no longer imports Flask: take it off KNOWN_FLASK")


def test_a_route_module_is_imported_from_outside_only_by_the_known_list():
    found = {_stem(rel) for rel in MODULES
             if not rel.startswith("api/") and any(_root(n) == "api" for n in _all(rel))}
    assert found - {"app", "views"} - KNOWN_API == set(), (
        "a module outside api/ began importing a route module")
    assert KNOWN_API - found == set(), (
        "no longer imports a route module: take it off KNOWN_API")


def test_what_a_relay_box_loads_needs_nothing_else_from_this_tree():
    """At module level the hub and every engine import the standard library,
    `settings` and each other only; the two importer halves a relay uses
    import nothing of ours at all. Anything more is imported where it is
    used, so a box without it can still load the module."""
    stdlib = set(sys.stdlib_module_names)
    wrong = {}
    for rel in MODULES:
        if rel == "signals.py" or rel.startswith("engines/"):
            top, _ = MODULES[rel]
            extra = sorted(n for n in top
                           if _root(n) not in stdlib and n != "settings"
                           and _root(n) != "engines" and not n.startswith("."))
            if extra:
                wrong[rel] = extra
    for rel in RELAY_LOADS[1:]:
        ours = {_stem(m).split("/")[0] for m in MODULES}
        extra = sorted(n for n in _all(rel) if _root(n) in ours and _root(n) != "importers")
        if extra:
            wrong[rel] = extra
    assert wrong == {}


# ── who reads the environment ────────────────────────────────────────────────
#: Modules that may read `os.environ`: the two that exist to (every setting is
#: named and parsed in `settings`, every renamed one resolved in `envnames`).
ENV_READERS = {"settings", "envnames"}

#: Modules that read the environment themselves today. Some are layered
#: readers by design (`integrations`, `auth_config`: the stored value first,
#: then the environment), some are a path or a secret looked up where it is
#: used. A new module reading the environment for itself fails; so does one
#: listed here that has stopped. Shrinks only.
KNOWN_ENV = {
    "alert_send", "api/v2/admin_directory", "api/v2/admin_sources", "api/v2/manifest",
    "auth_config", "auth_routes", "cli", "crypto_at_rest", "demofigures",
    "gunicorn.conf", "integrations", "ldap_backend", "metrics", "signals",
    "store/__init__", "theme",
}


def _reads_the_environment(path):
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    return any(isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
               and node.value.id == "os" and node.attr in ("environ", "getenv")
               for node in ast.walk(tree))


def test_the_environment_is_read_by_the_known_modules_and_no_others():
    """A setting parsed where it is used is how `true` came to mean yes in one
    module and nothing in the next. New settings go through `settings`."""
    found = {_stem(rel) for rel in MODULES
             if _reads_the_environment(os.path.join(WEB, *rel.split("/")))}
    assert found - ENV_READERS - KNOWN_ENV == set(), (
        "a module began reading os.environ itself: read it in settings.py")
    assert KNOWN_ENV - found == set(), (
        "no longer reads the environment: take it off KNOWN_ENV")
