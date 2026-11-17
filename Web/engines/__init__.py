"""The status sources, one module each (2026-11-16).

`base.py` holds what they share: the adapter contract, the marker states and
the feed shape. `registry.py` is where each source declares itself: its name,
its label, the setting it needs, what it answers for and how it is built.
`signals.py` imports every adapter back, builds the ones the
settings name, and merges what they return. Nothing here imports `signals`,
and nothing here imports beyond the standard library and `settings` at module
load: a relay box runs these with no web stack beside them.
"""
