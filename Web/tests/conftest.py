"""Shared test setup.

Two things, both about isolation.

**A writable temp root.** `tmp_path` defaults under the system temp directory,
which is not always writable in a sandbox, and several suites want a scratch
dataset. `pytest.ini` points `--basetemp` at a directory beside the tests.

**Environment that no suite should inherit.** Each test module sets its own
db/ingest configuration at import time, because `app.py` used to read config
at import. That is why the suite once passed file by file and failed as a
whole: whichever module imported `app` first decided the backend for the
entire run.

`create_app()` now exists, and the suites build their own app with
`appfixture.fresh_app`. Each module declares its environment as
`ATLAS_TEST_ENV`; the fixture below applies it before each test of that
module and puts back what was there after, which stops one suite's settings
leaking into the next.
"""

import os
import sys

import pytest

#: THE THEME (v1.48.0). The suite runs as the internal image does (its
#: Dockerfile stage sets ATLAS_THEME=lab): several suites key on the real
#: lab's wording. test_theme.py covers the plain theme on its own. Set before
#: anything imports settings, which reads the theme at import.
os.environ.setdefault("ATLAS_THEME", "lab")
#: NAMES THAT CHANGED (v1.48.0). The suite speaks the neutral names even where
#: legacy_names.py would hand the old deployment its old header and group
#: defaults, so the same suite passes with or without that private file.
#: test_envnames.py covers the old names on their own.
os.environ.setdefault("ATLAS_HUB_AUTH_HEADER", "X-Hub-Auth")
os.environ.setdefault("ATLAS_DECOYS_KEY_HEADER", "X-Api-Key")
os.environ.setdefault("ATLAS_ADMIN_GROUP", "atlas-admins")

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WEB not in sys.path:
    sys.path.insert(0, WEB)

#: WHERE AN UNSET PATH LANDS (2026-11-18). With nothing said, `settings` keeps
#: the map at `/data/lab-data.json` and `store` keeps the db at
#: `sqlite:////data/atlas.db`: right for the image, where `/data` is the
#: volume. A test that forgot to say otherwise wrote there. On a Windows
#: checkout that is `\data` at the root of whichever drive the tree is on, and
#: one test passed "alone" only by making a database there. The two defaults
#: are pointed into this run's own scratch folder before anything imports
#: `settings`, so a forgotten path is a file nobody keeps, not one beside
#: somebody's real data. A module that declares its own still gets its own.
_UNSET = os.path.join(WEB, ".pytest-tmp", "unset-%d" % os.getpid())
try:
    os.makedirs(_UNSET, exist_ok=True)
except OSError:                               # a tree that cannot be written to
    import tempfile
    _UNSET = tempfile.mkdtemp(prefix="atlas-tests-unset-")
os.environ.setdefault("ATLAS_DATA", os.path.join(_UNSET, "lab-data.json"))
os.environ.setdefault(
    "ATLAS_DB_URL", "sqlite:///" + os.path.join(_UNSET, "atlas.db").replace(os.sep, "/"))


#: Modules that read the environment once, at import, and keep what they read
#: for the life of the process. `appfixture.fresh_app` reloads them, in this
#: order, each time a test builds an app.
_READ_ONCE = ("settings", "hub_auth.auth")


@pytest.fixture(autouse=True, scope="module")
def _atlas_modules(request):
    """Start each test module with the read-once modules as that module's own
    declared environment would have made them.

    The environment is put back around every test (below), but `settings` and
    `hub_auth.auth` are not the environment: they are what was read from it
    the last time something reloaded them, and that was whichever test built
    an app last, in whatever module ran before. A suite that patches
    `auth.AUTH_MODE` and trusts the rest of the module to be as it found it
    passed after its alphabetical neighbour and failed after a suite that had
    built a signed hub-mode app (found by running the modules shuffled,
    2026-11-18: six tests in the site reads' suite). Only modules already
    imported are reloaded; nothing is imported here.
    """
    import importlib

    declared = getattr(request.module, "ATLAS_TEST_ENV", None) or {}
    before = dict(os.environ)
    os.environ.update({name: str(value) for name, value in declared.items()})
    try:
        for name in _READ_ONCE:
            module = sys.modules.get(name)
            if module is not None:
                importlib.reload(module)
    finally:
        for name in [n for n in os.environ if n not in before]:
            del os.environ[name]
        for name, value in before.items():
            if os.environ.get(name) != value:
                os.environ[name] = value
    yield


@pytest.fixture(autouse=True)
def _atlas_env(request, monkeypatch):
    """Give each test the environment its own module declared, and take back
    everything the test did to the environment afterwards.

    pytest imports every test module before running any test, so the module
    that happened to import last owned `os.environ` for the whole run, and
    `store.session_scope()` reads `ATLAS_DB_URL` live, which is why suites
    passed alone and 401'd together. Each module declares `ATLAS_TEST_ENV`
    and it is re-applied here, per test.

    The declared values go in through `monkeypatch` (2026-11-17). A test that
    then calls `monkeypatch.setenv` on the same name has it put back to what
    was there before the test, whatever order the two fixtures are torn down
    in. Set straight into `os.environ`, the value a test's `monkeypatch`
    remembered as "the old one" was the declared one, and where another
    plugin's autouse fixture asks for `monkeypatch` first (pytest-django does)
    its undo ran after the restore below and left `ATLAS_AUTH_MODE=accounts`
    behind for the next module: the alerts suites followed by the db suite
    answered 401.

    The restore is the WHOLE environment, for EVERY test (2026-11-18). It was
    a hand-kept list of names, applied only to modules that declared an
    environment: `ATLAS_MAPS` was never on the list, a module with nothing
    declared got no restore at all, and `fresh_app(ATLAS_READONLY="1")` in
    one suite was still set when a later one ran. A list has to be remembered
    each time a setting is added; a snapshot does not.
    """
    before = dict(os.environ)
    for name, value in (getattr(request.module, "ATLAS_TEST_ENV", None) or {}).items():
        monkeypatch.setenv(name, str(value))
    yield
    for name in [n for n in os.environ if n not in before]:
        del os.environ[name]
    for name, value in before.items():
        if os.environ.get(name) != value:
            os.environ[name] = value


@pytest.fixture
def dataset_dir(tmp_path):
    """An empty directory to point ATLAS_DATA at."""
    out = tmp_path / "data"
    out.mkdir()
    return out


# ── Private-only tests ───────────────────────────────────────────────────────
#: True in the original deployment's own repo, False in the public tree (which
#: never carries legacy_names.py). A test marked `private_only` checks a file
#: or a dataset that exists only there, such as the proxy trust map or the
#: real map's own rites, and is skipped everywhere else.
PRIVATE_TREE = os.path.exists(os.path.join(WEB, "legacy_names.py"))


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "private_only: needs the original deployment's private files or dataset")
    _own_basetemp(config)


#: `pytest.ini` pins the scratch root beside the suite. pytest empties that
#: directory when a run starts, so two runs of one checkout at once (two
#: sessions, or a run started while another is going) deleted each other's
#: files mid-test. Each run now works in its own folder under it.
_SHARED_BASETEMP = ".pytest-tmp"
_STALE_RUN_SECONDS = 24 * 3600


def _own_basetemp(config):
    """Move a run that was given the shared scratch root into `run-<pid>` under
    it, and clear out what runs older than a day left behind. A run given any
    other `--basetemp` is left exactly as asked."""
    import shutil
    import time

    given = getattr(config.option, "basetemp", None)
    if not given or os.path.normpath(str(given)) != _SHARED_BASETEMP:
        return
    if hasattr(config, "workerinput"):        # an xdist worker: the controller chose
        return
    root = os.path.join(str(config.rootpath), _SHARED_BASETEMP)
    try:
        os.makedirs(root, exist_ok=True)
        cutoff = time.time() - _STALE_RUN_SECONDS
        for name in os.listdir(root):
            old = os.path.join(root, name)
            if name.startswith(("run-", "unset-")) and os.path.getmtime(old) < cutoff:
                shutil.rmtree(old, ignore_errors=True)
    except OSError:
        return                                # an unwritable root is pytest's to report
    config.option.basetemp = os.path.join(root, "run-%d" % os.getpid())


def pytest_sessionfinish(session, exitstatus):
    """A run that passed has nothing in its scratch folder worth keeping; one
    that failed keeps it to be looked at, until it is a day old."""
    import shutil
    import time

    if exitstatus != 0:
        return
    store = sys.modules.get("store")
    if store is not None:                     # let go of the scratch database
        try:
            store.reset_engine_for_tests()
        except Exception:                     # noqa: BLE001 - tidying only
            pass
    done = [_UNSET]
    own = getattr(session.config.option, "basetemp", None)
    if own and os.path.basename(str(own)) == "run-%d" % os.getpid():
        done.append(str(own))
    # A network share answers "not empty" for a folder whose files it has not
    # finished deleting, so one pass can leave most of the tree: ask again.
    for folder in done:
        for _ in range(5):
            shutil.rmtree(folder, ignore_errors=True)
            if not os.path.isdir(folder):
                break
            time.sleep(0.4)


def pytest_terminal_summary(terminalreporter):
    """Say which order a shuffled run used, so a failure can be run again."""
    seed = os.environ.get("ATLAS_TEST_SHUFFLE")
    if seed:
        terminalreporter.write_line(
            "ATLAS_TEST_SHUFFLE=%s: the test modules ran in a shuffled order" % seed)


def _shuffled_by_module(items, seed):
    """The same tests, each module's own order kept, the modules in an order
    drawn from `seed`. A suite that only passes in alphabetical order is
    leaning on what an earlier module left behind; this is how to find out."""
    import random

    groups, order = {}, []
    for item in items:
        key = item.nodeid.split("::", 1)[0]
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(item)
    random.Random(str(seed)).shuffle(order)
    return [item for key in order for item in groups[key]]


def pytest_collection_modifyitems(config, items):
    seed = os.environ.get("ATLAS_TEST_SHUFFLE")
    if seed:
        items[:] = _shuffled_by_module(items, seed)
    if PRIVATE_TREE:
        return
    skip = pytest.mark.skip(reason="private tree only (not part of the public build)")
    for item in items:
        if "private_only" in item.keywords:
            item.add_marker(skip)
