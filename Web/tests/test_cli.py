"""atlasctl end-to-end tests — run directly, no pytest needed:

    python Web/tests/test_cli.py

Drives the real CLI entrypoint (in-process) through the §4 contract:
initdb -> import-json -> export -> deep-compare, plus sites listing,
--strict refusal, and unknown-site errors.
"""

import json
import os
import sys
import tempfile

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WEB)

TMP = tempfile.mkdtemp(prefix="atlas-cli-test-")
DB = "--db", "sqlite:///" + os.path.join(TMP, "cli.db").replace("\\", "/")
GOLDEN_PATH = os.path.join(WEB, "default-lab-data.json")
with open(GOLDEN_PATH, encoding="utf-8") as f:
    GOLDEN = json.load(f)

import cli  # noqa: E402

assert cli.main([*DB, "initdb"]) == 0  # tables exist regardless of test order


def test_initdb_import_export_round_trip():
    # --keep-stamps: the file is the record, so nothing is added to it
    assert cli.main([*DB, "import-json", "--site", "lab", "--keep-stamps", GOLDEN_PATH]) == 0
    out_path = os.path.join(TMP, "export.json")
    assert cli.main([*DB, "export", "--site", "lab", "-o", out_path]) == 0
    with open(out_path, encoding="utf-8") as f:
        assert json.load(f) == GOLDEN, "CLI round-trip diverged from source dataset"


def test_a_plain_import_marks_each_new_place_unchecked_and_changes_nothing_else():
    assert cli.main([*DB, "import-json", "--site", "stamped", GOLDEN_PATH]) == 0
    out_path = os.path.join(TMP, "stamped.json")
    assert cli.main([*DB, "export", "--site", "stamped", "-o", out_path]) == 0
    with open(out_path, encoding="utf-8") as f:
        out = json.load(f)
    for node in out["nodes"]:
        mark = node.pop("provenance")
        assert mark["reviewed"] is False and mark["source"] == "import-json" and mark["charted_by"] == "cli"
    assert out == GOLDEN
    # the same file again adds nothing new: no place is re-charted or marked changed
    assert cli.main([*DB, "import-json", "--site", "stamped", GOLDEN_PATH]) == 0
    assert cli.main([*DB, "export", "--site", "stamped", "-o", out_path]) == 0
    with open(out_path, encoding="utf-8") as f:
        again = json.load(f)
    assert all(n["provenance"]["charted_at"] == n["provenance"]["changed_at"] for n in again["nodes"])


def test_sites_lists_the_site():
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert cli.main([*DB, "sites"]) == 0
    assert "lab" in buf.getvalue()


def test_strict_refuses_problem_dataset_and_leaves_no_site():
    bad = json.loads(json.dumps(GOLDEN))
    bad["nodes"][0]["zone"] = "no-such-zone"
    bad_path = os.path.join(TMP, "bad.json")
    with open(bad_path, "w", encoding="utf-8") as f:
        json.dump(bad, f)
    assert cli.main([*DB, "import-json", "--site", "strict-site", "--strict", bad_path]) == 3
    assert cli.main([*DB, "export", "--site", "strict-site"]) == 2, "strict import must not create the site"
    # without --strict the same dataset imports (tolerance doctrine)
    assert cli.main([*DB, "import-json", "--site", "tolerant-site", bad_path]) == 0


def test_export_unknown_site_errors():
    assert cli.main([*DB, "export", "--site", "no-such-site"]) == 2


def test_unreadable_dataset_errors():
    assert cli.main([*DB, "import-json", os.path.join(TMP, "missing.json")]) == 2


if __name__ == "__main__":
    failures = 0
    for name in sorted(n for n in globals() if n.startswith("test_")):
        try:
            globals()[name]()
            print(f"  ok   {name}")
        except AssertionError as e:
            failures += 1
            print(f"  FAIL {name}: {e}")
    print("PASS" if not failures else f"{failures} FAILURE(S)")
    sys.exit(1 if failures else 0)


def test_import_netbox_reports_an_unreadable_token_file_instead_of_crashing():
    import argparse
    saved = {k: os.environ.pop(k, None) for k in ("NETBOX_TOKEN", "NETBOX_TOKEN_FILE")}
    os.environ["NETBOX_TOKEN_FILE"] = os.path.join(TMP, "no-such-token-file")
    try:
        args = argparse.Namespace(token=None, token_file=None)
        assert cli.cmd_import_netbox(args) == 2
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_a_db_command_on_a_database_with_no_tables_says_what_to_do(tmp_path, capsys):
    url = f"sqlite:///{(tmp_path / 'empty.db').as_posix()}"
    assert cli.main(["--db", url, "sites"]) == 2
    assert "db backend" in capsys.readouterr().err
