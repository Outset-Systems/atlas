"""External inventory importers (Atlas for Teams, the design notes).

Two kinds live here. The connection modules (`wire.py` says what each must
provide) only read: they turn a system's answer into candidates for
`review.py`, and what an admin ticks is written by the store, not by them.

The doctrine below holds for `netbox.sync`, `csv_import.import_rows` and the
nmap importer, which write to the database themselves, and is distinct from
the authoritative import-json path:
- upserts keyed on (site, external_source, external_ref) — never delete;
  rows missing from a re-import are flagged status='retired' (NetBox always,
  CSV only when asked to with `retire_missing`; a scan never retires anything)
- hand-edits win: existing lore, links, scroll, and any position a human set
  (or locked) are never overwritten
- fetch everything first, write in one transaction — a half-import must not
  eat a map
"""
