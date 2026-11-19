"""Every field in the catalogue says what it is to a viewer who may not see
everything (`schema.HIDING`), so none reaches a restricted viewer unread.

The refactor's stage 4. Before this, a field was given to every viewer until
someone remembered to hide it: the 11-12 audit found a rite's key, a
certificate's host and a rack slot's words open that way. A new field now
fails here until it is declared, and `redaction.py` reads the declaration.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import schema  # noqa: E402

ATLAS_TEST_ENV = {"ATLAS_AUTH_MODE": "standalone"}


def _every_field():
    for key, sec in schema.SECTIONS.items():
        for fld in sec["fields"]:
            yield key, fld["name"], None
            for sub in fld.get("of") or []:
                yield key, fld["name"], sub["name"]


def test_every_field_says_what_it_is_to_a_restricted_viewer():
    unsaid = [f"{key}.{name}" + (f".{sub}" if sub else "")
              for key, name, sub in _every_field()
              if schema.hiding(key, name, sub) not in schema.HIDING_KINDS | {"parts"}]
    assert unsaid == [], (
        "declare these in schema.HIDING (safe, ref, words, slug, url, keys, pins, admin):\n  "
        + "\n  ".join(unsaid))


def test_a_declaration_names_only_fields_that_exist_and_kinds_that_do():
    """A declaration left behind by a renamed field would hide nothing and say
    it does."""
    stale = []
    for key, said in schema.HIDING.items():
        assert key in schema.SECTIONS, key
        if said == "admin":
            continue
        for name, kind in said.items():
            fld = schema.field(key, name)
            if fld is None:
                stale.append(f"{key}.{name}")
                continue
            if isinstance(kind, dict):
                subs = {s["name"] for s in fld.get("of") or []}
                stale += [f"{key}.{name}.{s}" for s in kind if s not in subs]
                assert set(kind.values()) <= schema.HIDING_KINDS, (key, name)
            else:
                assert kind in schema.HIDING_KINDS, (key, name, kind)
    assert stale == []


def test_every_section_is_declared_and_the_drop_list_names_sections():
    assert set(schema.HIDING) == set(schema.SECTIONS)
    assert schema.WORDS_DROP_ENTRY <= set(schema.SECTIONS)


def test_a_field_that_names_a_place_by_id_is_a_reference():
    for key, name, sub in _every_field():
        fld = schema.field(key, name)
        target = next(s for s in fld["of"] if s["name"] == sub) if sub else fld
        if target.get("ref") == "nodes":
            # an admin-only section or field stays admin-only, references and all
            assert schema.hiding(key, name, sub) in ("ref", "admin"), (key, name, sub)
