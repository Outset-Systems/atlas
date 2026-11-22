#!/usr/bin/env python3
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "configuration.md"
SCAN = [ROOT / "Web", ROOT / "relay"]
SKIP_FILES = set()
SKIP_DIRS = {"tests", "__pycache__", ".pytest-tmp", "node_modules", "vendor"}

ENV_NAME = re.compile(r"^(?:ATLAS|HUB|NETBOX|PROMETHEUS)_[A-Z0-9_]+$")
READERS = {"get", "getenv", "env", "is_set", "flag", "_cfg", "_read_secret", "_env", "secret"}
SECRET_READERS = {"_read_secret", "secret"}
NAME_LISTS = {"ALLOWED", "SECRETS", "GROUPS", "DEFAULTS", "URLS", "BOOLS"}


def _const_str(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _strings_in(node):
    for sub in ast.walk(node):
        s = _const_str(sub)
        if s is not None:
            yield s


def _is_environ(node):
    if isinstance(node, ast.Attribute) and node.attr == "environ":
        return True
    return isinstance(node, ast.Name) and node.id == "environ"


def names_in(path):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as e:
        sys.exit(f"cannot parse {path}: {e}")
    found, secrets = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and _is_environ(node.value):
            s = _const_str(node.slice)
            if s:
                found.add(s)
        elif isinstance(node, ast.Compare) and any(_is_environ(c) for c in node.comparators):
            s = _const_str(node.left)
            if s:
                found.add(s)
        elif isinstance(node, ast.Call) and node.args:
            func = node.func
            fname = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if fname not in READERS:
                continue
            s = _const_str(node.args[0])
            if not s or not ENV_NAME.match(s):
                if not (s and isinstance(func, ast.Attribute) and _is_environ(func.value)):
                    continue
            found.add(s)
            if fname in SECRET_READERS:
                secrets.add(s)
        elif isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if not any(t in NAME_LISTS for t in targets):
                continue
            listed = {s for s in _strings_in(node.value) if ENV_NAME.match(s) or s == "HUB_URL"}
            found |= listed
            if "SECRETS" in targets:
                secrets |= listed
    for node in ast.walk(tree):
        s = _const_str(node)
        if s and ENV_NAME.match(s):
            found.add(s)
    return found, secrets


def collect():
    found, secrets, where = set(), set(), {}
    for base in SCAN:
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            rel = path.relative_to(ROOT)
            if path.name in SKIP_FILES or SKIP_DIRS & set(rel.parts):
                continue
            f, s = names_in(path)
            for name in f:
                where.setdefault(name, rel.as_posix())
            found |= f
            secrets |= s
    for name in secrets:
        found.add(name + "_FILE")
        where.setdefault(name + "_FILE", "(secret file variant of " + name + ")")
    found = {n for n in found if not n.endswith("_")}
    return found, where


def documented():
    text = DOC.read_text(encoding="utf-8")
    return set(re.findall(r"`([A-Z][A-Z0-9_]+)`", text))


def main():
    if not DOC.exists():
        sys.exit(f"missing {DOC.relative_to(ROOT)}")
    found, where = collect()
    docs = documented()
    missing = sorted(found - docs)
    print(f"env-coverage: {len(found)} variables read by the code, "
          f"{len(found & docs)} documented in {DOC.relative_to(ROOT).as_posix()}")
    if missing:
        print("\nNot documented:")
        for name in missing:
            print(f"  {name:<40} {where.get(name, '')}")
        return 1
    extra = sorted(n for n in docs - found if ENV_NAME.match(n) or n == "HUB_URL")
    if extra:
        print("note: documented but not found in the code (check they still exist): "
              + ", ".join(extra))
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
