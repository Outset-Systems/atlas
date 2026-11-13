"""Typed request bodies for v2 — pydantic, used sparingly.

Only the fixed-shape write envelopes are modelled; every dynamic or
redaction-shaped body (the dataset, the feeds) deliberately is not (§5 H2 —
`schema.py`'s catalogue is the source of truth for the dataset and a pydantic
mirror of it would be a second one).

One deviation from the framework note, recorded here and in the plan: models
are applied INSIDE handlers (`Model.model_validate` + a one-sentence
`{"error": …}` body on failure) rather than through `@api.validate`
decorators. That began as parity: spectree's auto-rejection would have
answered with its own envelope where v1's exact sentence was the contract. v1
was removed in v1.41.0 and the decorators did not follow; spectree was dropped
from the requirements, never imported, and the sentence is what the front end
shows.
"""

from pydantic import RootModel


class OverlayWrite(RootModel[dict]):
    """G2 · `POST /api/v2/positions` / `/api/v2/rack` — an object of
    key -> value (node id -> {x, y}; rack slot key -> {u}). The VALUES stay
    untyped on purpose: `Overlay.merge` is the validator that counts, and it
    already ignores unknown keys and clamps what it keeps."""
