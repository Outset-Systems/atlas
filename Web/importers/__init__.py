"""External inventory importers (Atlas for Teams, the design notes).

Shared doctrine, distinct from the authoritative import-json path:
- upserts keyed on (site, external_source, external_ref) — never delete;
  rows missing from a re-import are flagged status='retired'
- hand-edits win: existing lore, links, scroll, and any position a human set
  (or locked) are never overwritten
- fetch everything first, write in one transaction — a half-import must not
  eat a map
"""
