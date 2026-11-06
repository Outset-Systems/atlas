"""THE THEME (v1.48.0) — every word and picture that names one particular lab.

The Atlas grew up as one lab's map, so its chrome spoke that lab's language:
the veil's sigil, the colophon, which switch "feeds" the relays, which host
"divides its memory among its vassals", the emblem on each place's card. None
of that belongs to the app. It lives in `themes/<name>.json`, picked by
`ATLAS_THEME`:

  plain   (default) names nothing — what a stranger's install shows
  lab  the owner's own lab; the internal image sets it in the Dockerfile

A theme file only needs the keys it changes; everything else falls back to
`plain.json`, so a new key added there can never leave another theme with a
hole in its page. An unknown name falls back to plain and says so in the log.
"""
import copy
import json
import logging
import os
import re

log = logging.getLogger("atlas.web.theme")

HERE = os.path.dirname(os.path.abspath(__file__))
THEMES_DIR = os.path.join(HERE, "themes")
DEFAULT = "plain"
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")


def _read(name):
    with open(os.path.join(THEMES_DIR, f"{name}.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _merge(base, over):
    out = copy.deepcopy(base)
    for key, value in (over or {}).items():
        if key.startswith("_"):
            continue
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load(name=None):
    """The theme `name` (default: $ATLAS_THEME, else plain), merged over plain."""
    name = (name if name is not None else os.environ.get("ATLAS_THEME", "")).strip().lower() or DEFAULT
    plain = {k: v for k, v in _read(DEFAULT).items() if not k.startswith("_")}
    if name == DEFAULT:
        return DEFAULT, plain
    if not _NAME_RE.match(name):
        log.warning("ATLAS_THEME=%r is not a theme name; using plain", name)
        return DEFAULT, plain
    try:
        return name, _merge(plain, _read(name))
    except (OSError, ValueError):
        log.warning("theme %r could not be read; using plain", name, exc_info=True)
        return DEFAULT, plain


NAME, T = load()


def text(key):
    return T["text"].get(key, "")


def foreign_maps():
    """Bundled renders that belong to some OTHER theme's map set. They stay
    resolvable (a dataset may still name one), but the viewer's gallery does
    not offer them, unless the theme invites one with `guest_maps`."""
    own = set(T.get("maps") or []) | set(T.get("guest_maps") or []) | {T.get("map_art")}
    other = set()
    try:
        names = os.listdir(THEMES_DIR)
    except OSError:
        return set()
    for fname in names:
        if not fname.endswith(".json") or fname[:-5] == NAME:
            continue
        try:
            data = _read(fname[:-5])
        except (OSError, ValueError):
            continue
        other |= set(data.get("maps") or [])
        if data.get("map_art"):
            other.add(data["map_art"])
    return other - own


def map_label(name):
    """The theme's own name for one of its renders, or ''."""
    return (T.get("map_labels") or {}).get(name, "")


def client():
    """The part of the theme the browser needs (config.js reads it as CFG.THEME)."""
    logos = {str(k): str(v) for k, v in (T.get("node_logos") or {}).items()
             if _SLUG_RE.match(str(v))}
    return {
        "name": NAME,
        "text": dict(T["text"]),
        "nodeLogos": logos,
        # emblems that belong to the theme's own map: on another map style they stand down
        "sceneryLogos": [str(s) for s in T.get("scenery_logos") or [] if _SLUG_RE.match(str(s))],
        "foldedZones": [str(z) for z in T.get("folded_zones") or []],
        "forgeNames": [str(n).lower() for n in T.get("forge_names") or []],
        "gatewayNodes": [str(n) for n in T.get("gateway_nodes") or []],
        "standardWords": dict(T.get("standard_words") or {}),
        "tripwire": "eye" if T.get("tripwire_icon") == "eye" else "bird",
    }
