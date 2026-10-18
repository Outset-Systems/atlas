"""Typed request bodies for v2 — pydantic, used sparingly.

Only the fixed-shape write envelopes are modelled; every dynamic or
redaction-shaped body (the dataset, the feeds) deliberately is not (§5 H2 —
`schema.py`'s catalogue is the source of truth for the dataset and a pydantic
mirror of it would be a second one).

One deviation from the framework note, recorded here and in the plan: models
are applied INSIDE handlers (`Model.model_validate` + the v1 error body on
failure) rather than through `@api.validate` decorators, because spectree's
auto-rejection would answer with its own envelope where parity demands v1's
exact `{"error": …}` sentence. The decorators can come at cutover, when the v1
body stops being the contract.
"""

from pydantic import RootModel


class OverlayWrite(RootModel[dict]):
    """G2 · `POST /api/v2/positions` / `/api/v2/rack` — an object of
    key -> value (node id -> {x, y}; rack slot key -> {u}). The VALUES stay
    untyped on purpose: `Overlay.merge` is the validator that counts, and it
    already ignores unknown keys and clamps what it keeps."""
