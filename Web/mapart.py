"""The picture the map is drawn on, and how it gets replaced.

The base render was `static/map/plain.png`, hard-coded in the template since
the first commit. That was fine while the Atlas was one lab's map and wrong the
moment it was anything else: a floor plan, a rack elevation, a site photo, a
different fantasy coastline, or simply the next render of this one. The places
are positioned in fractions of the image, so swapping the picture keeps every
marker where it was — the map is the data, the art is a backdrop.

**Nothing here decodes an image.** `sniff()` reads magic bytes and that is the
whole extent of it, which is why the app needs no image library and why
converting the backdrop (the backdrop conversion script) is an offline step run
wherever the art is authored, not something the container does.

**Two sources, one name.** `meta.map_image` holds a bare filename. It resolves
against the images baked into the image first, then against uploads under
`/data/maps/`. Bundled art therefore keeps working with no upload, an upload
can shadow nothing it shouldn't, and the dataset stays a text file you can diff.

**Why uploads are checked by their bytes.** An extension is a claim by whoever
is uploading. These files are served back from the app's own origin, so a file
that says `.png` and contains markup is a stored-XSS delivery mechanism —
`image/svg+xml` especially, which browsers execute script inside. SVG is
refused outright and everything else must begin with the magic number for a
raster format the browser will only ever decode as an image.
"""

import json
import logging
import math
import mimetypes
import os
import re

import settings
from jsonio import write_bytes_atomic, write_json_atomic

log = logging.getLogger("atlas.data.mapart")

# CPython's built-in table knows `.avif` and does **not** know `.webp`
# (verified on 3.12), and Debian slim ships no `/etc/mime.types` to fill the
# gap — so Flask's static route would serve the bundled backdrop as
# `application/octet-stream` and the browser would offer to *download* the map
# instead of drawing it. Registered here, beside SIGNATURES, so "the formats
# the Atlas serves" stays one list in one file: the next format added below
# gets its mimetype in the same edit, not re-discovered in production.
mimetypes.add_type("image/webp", ".webp")

#: Art shipped inside the container image.
BUNDLED_DIR = os.path.join(settings.HERE, "static", "map")

#: A map style's sidecar: `<art>.style.json` beside `<art>.webp`, written by the
#: operator and never uploaded (`save` only takes pictures). It may name the
#: style and give it zoom regions of its own, because a region is a rectangle
#: on one particular picture: the dataset's regions fit the realm's own art and
#: mean nothing on another. Region art named here is reached by zooming in, so
#: the gallery does not offer it as a backdrop. `places` and `zones` move the
#: markers and the network names on this picture, for the same reason, and
#: `logos` gives a place the emblem it wears on this picture (`{"id": "wolf"}`,
#: an icon in static/icons): a theme's own scenery stays on the theme's map.
#: The operator writes it by hand, or an admin drags the dots on the style and
#: saves (`save_layout`), which touches only the spots.
STYLE_SUFFIX = ".style.json"
MAX_STYLE_WORDS = 40
STYLE_WORD_KEY = re.compile(r"(?:[^\W\d_]|[' ’-]){2,30}")
STYLE_WORD = re.compile(r"(?:[^\W_]|[' ’-]){1,30}")
MAX_STYLE_REGIONS = 32
MAX_STYLE_POINTS = 512
#: The range a dragged dot may take: the table, plus the sky and the black band.
STYLE_POINT_RANGE = (-40, 140)
_REGION_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

#: The most a base render may weigh. A 2048×2048 PNG is ~4 MB; this leaves
#: room for a big photographic backdrop without letting the volume fill.
MAX_BYTES = 24 * 1024 * 1024

#: Formats a browser will only ever decode as a picture, by their magic bytes.
#: SVG is deliberately absent — it is a document that can carry script, and
#: these are served same-origin.
SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
)

#: The default, and what an unconfigured map still shows.
#:
#: WEBP since 2026-07-31. The render was a 2048² **RGBA** PNG — an alpha channel
#: on a render whose alpha was 255 everywhere, in a codec built for flat colour
#: and sharp edges, carrying a painterly image. **7.91 MB → 1.10 MB** at WebP
#: q=95 (SSIM 0.989, PSNR 43.7 dB, worst channel delta 10/255; in the smoothest
#: third of the image — banding country — 99.9% of pixels land within 6/255).
#: the owner's call, 2026-07-31. Regenerate or re-tune with
#: the backdrop conversion script; omit `-q` there for a bit-exact lossless
#: encode, which is 3.94 MB.
#:
#: A new filename rather than an overwrite of the *PNG*, because the map `<img>`
#: carries no `?v=` cache-buster (the design notes 2026-07-24). The `.webp` itself was
#: re-encoded in place from lossless to q=95 within the same unreleased version,
#: so no deployment ever saw the first one.
import theme as _theme

# The bundled backdrop when a dataset names none: the theme's (THE THEME, v1.48.0).
DEFAULT = _theme.T["map_art"]

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def safe_name(name):
    """A filename that cannot escape its directory, or None.

    Rejects rather than sanitises: silently rewriting `../../etc/passwd` into
    `etc-passwd` produces a file nobody asked for under a name nobody typed.
    """
    name = (name or "").strip()
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return None
    if ".." in name:
        return None
    return name if _SAFE_NAME.match(name) else None


def sniff(head):
    """The format these opening bytes actually are, or None.

    WEBP needs both ends of its header checked — `RIFF` alone is any of a
    dozen container formats.
    """
    for signature, kind in SIGNATURES:
        if head.startswith(signature):
            return kind
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


def resolve(name):
    """`(path, is_bundled)` for a configured map image, or `(None, False)`.

    Bundled art wins, so an upload can never shadow the render the container
    ships with — which is what a confused deployment would otherwise do to
    itself the moment someone uploaded a file named like the shipped render.

    "Nowhere" is the honest answer for both an unsafe name and one that simply
    isn't there, and the caller decides what to draw instead. Substituting the
    default in here would have made `resolve("../../etc/passwd")` report
    success, which is a confusing thing for a path resolver to do.
    """
    safe = safe_name(name)
    if not safe:
        return None, False
    bundled = os.path.join(BUNDLED_DIR, safe)
    if os.path.isfile(bundled):
        return bundled, True
    uploaded = os.path.join(settings.MAPS_DIR, safe)
    if os.path.isfile(uploaded):
        return uploaded, False
    return None, False


def url_of(name, bundled):
    """Where the browser fetches a render: bundled art is served from static/,
    uploads from /map-art/."""
    return f"static/map/{name}" if bundled else f"map-art/{name}"


def _style_points(raw):
    """{id: {x, y}} from a sidecar's `places` or `zones`, well-formed entries only."""
    if not isinstance(raw, dict):
        return {}
    low, high = STYLE_POINT_RANGE
    points = {}
    for key, at in list(raw.items())[:MAX_STYLE_POINTS]:
        if not _REGION_ID.match(str(key)) or not isinstance(at, dict):
            continue
        x, y = at.get("x"), at.get("y")
        if all(isinstance(v, (int, float)) and not isinstance(v, bool)
               and math.isfinite(v) and low <= v <= high for v in (x, y)):
            points[key] = {"x": x, "y": y}
    return points


#: Where the card's emblems live; a sidecar may only name one that is there.
ICONS_DIR = os.path.join(settings.HERE, "static", "icons")
_ICON_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")


def _style_logos(raw):
    """{place id: icon slug} from a sidecar's `logos`, for icons the Atlas has."""
    if not isinstance(raw, dict):
        return {}
    out = {}
    for key, slug in list(raw.items())[:MAX_STYLE_POINTS]:
        if (_REGION_ID.match(str(key)) and isinstance(slug, str) and _ICON_SLUG.match(slug)
                and os.path.isfile(os.path.join(ICONS_DIR, slug + ".svg"))):
            out[key] = slug
    return out


def _style_region(raw):
    """One sidecar region in the dataset's shape plus its `url`, or None."""
    if not isinstance(raw, dict) or not _REGION_ID.match(str(raw.get("id") or "")):
        return None
    name = str(raw.get("name") or "").strip()
    art, bundled = resolve(str(raw.get("map") or ""))
    rect = [raw.get(key) for key in ("x", "y", "w", "h")]
    if not name or not art or not all(
            isinstance(v, (int, float)) and not isinstance(v, bool) for v in rect):
        return None
    filename = os.path.basename(art)
    region = dict(zip(("x", "y", "w", "h"), rect), id=raw["id"], name=name, map=filename,
                  url=url_of(filename, bundled), auto=raw.get("auto") is True)
    if raw.get("parent"):
        region["parent"] = str(raw["parent"])
    if raw.get("fold") is True:
        region["fold"] = True          # on its parent's map, only the places that speak outside it
    pins = _style_points(raw.get("places"))
    if pins:
        region["places"] = pins
    return region


def _style_words(raw):
    """The words a style speaks, word for word. Both sides stay plain words,
    because the page sets them as markup. words-model.js checks the same."""
    if not isinstance(raw, dict):
        return {}
    out = {}
    for key, value in list(raw.items())[:MAX_STYLE_WORDS]:
        key = str(key).strip().lower()
        if isinstance(value, str) and STYLE_WORD_KEY.fullmatch(key) and STYLE_WORD.fullmatch(value.strip()):
            out[key] = value.strip()
    return out


def style(name):
    """What the sidecar beside render `name` says, as {label, regions}; an
    empty answer when there is no sidecar or it cannot be read. A broken
    sidecar costs a style its zoom, never the map."""
    safe = safe_name(name)
    if not safe:
        return {}
    filename = safe.rsplit(".", 1)[0] + STYLE_SUFFIX
    for directory in (BUNDLED_DIR, settings.MAPS_DIR):
        path = os.path.join(directory, filename)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as handle:
                raw = json.load(handle)
            if not isinstance(raw, dict):
                raise ValueError("not an object")
        except (OSError, ValueError) as e:
            log.warning("map style %s is unreadable: %s", filename, e)
            return {}
        found = raw.get("regions") if isinstance(raw.get("regions"), list) else []
        regions = [r for r in map(_style_region, found[:MAX_STYLE_REGIONS]) if r]
        if len(regions) != len(found):
            log.warning("map style %s: kept %d of %d regions", filename, len(regions), len(found))
        return {"label": str(raw.get("label") or "").strip(), "regions": regions,
                "bright": raw.get("bright") is True,
                "words": _style_words(raw.get("words")),
                "tripwire": "eye" if raw.get("tripwire") == "eye" else "bird",
                "places": _style_points(raw.get("places")),
                "zones": _style_points(raw.get("zones")),
                "logos": _style_logos(raw.get("logos"))}
    return {}


def save_layout(name, body):
    """Merge dragged spots into the sidecar beside uploaded render `name`, so
    the places stand there for every viewer of that style. Returns how many
    spots were written.

    `body` is `{places, zones, regions: {region id: places}}`, each an
    `{id: {x, y}}` checked by `_style_points`. Everything else in the sidecar
    stays as the operator wrote it. A region the sidecar does not list is
    skipped: this moves dots, it never draws a region. Raises ValueError with
    a sentence for the editor.
    """
    safe = safe_name(name)
    path, bundled = resolve(safe) if safe else (None, False)
    if not path:
        raise ValueError("no such map image")
    filename = safe.rsplit(".", 1)[0] + STYLE_SUFFIX
    if bundled or os.path.isfile(os.path.join(BUNDLED_DIR, filename)):
        raise ValueError("this map style is built into the Atlas, so its layout is part of the image")
    if not isinstance(body, dict):
        raise ValueError("expected an object of places, zones and regions")
    target = os.path.join(settings.MAPS_DIR, filename)
    raw = {}
    if os.path.isfile(target):
        try:
            with open(target, encoding="utf-8") as handle:
                raw = json.load(handle)
        except (OSError, ValueError) as e:
            raise ValueError(f"the sidecar {filename} cannot be read, so it was left alone: {e}") from e
        if not isinstance(raw, dict):
            raise ValueError(f"the sidecar {filename} is not an object, so it was left alone")
    written = 0
    for key in ("places", "zones"):
        points = _style_points(body.get(key))
        if points:
            raw[key] = {**(raw.get(key) if isinstance(raw.get(key), dict) else {}), **points}
            written += len(points)
    pins = body.get("regions") if isinstance(body.get("regions"), dict) else {}
    for region in raw.get("regions") if isinstance(raw.get("regions"), list) else []:
        if not isinstance(region, dict):
            continue
        points = _style_points(pins.get(region.get("id")))
        if points:
            region["places"] = {**(region.get("places") if isinstance(region.get("places"), dict) else {}),
                                **points}
            written += len(points)
    if not written:
        return 0
    write_json_atomic(target, raw, keep_backup=False)
    log.info("map style %s: %d spots saved", filename, written)
    return written


def _region_art(directory):
    """The art a directory's sidecars zoom into: reachable, not a backdrop."""
    try:
        names = os.listdir(directory)
    except OSError:
        return set()
    return {region["map"]
            for name in names if name.endswith(STYLE_SUFFIX)
            for region in style(name[:-len(STYLE_SUFFIX)] + ".webp").get("regions", [])}


def available():
    """Every base render this Atlas could be pointed at, bundled first."""
    out = []
    foreign = _theme.foreign_maps()       # another theme's set: kept, not offered
    zoomed = _region_art(BUNDLED_DIR) | _region_art(settings.MAPS_DIR)
    for directory, bundled in ((BUNDLED_DIR, True), (settings.MAPS_DIR, False)):
        try:
            names = sorted(os.listdir(directory))
        except OSError:
            continue
        for name in names:
            path = os.path.join(directory, name)
            if not safe_name(name) or not os.path.isfile(path):
                continue
            if name.endswith(STYLE_SUFFIX) or name in zoomed:
                continue
            if bundled and name in foreign:
                continue
            if any(entry["name"] == name for entry in out):
                continue                    # bundled shadows an upload, as resolve() does
            out.append({"name": name, "bundled": bundled,
                        "bytes": os.path.getsize(path)})
    return out


def save(name, blob):
    """Store an uploaded render. Returns the stored name.

    Raises ValueError with a sentence a person can act on — this surfaces in
    the Desk, where "invalid input" would be useless.
    """
    safe = safe_name(name)
    if not safe:
        raise ValueError(
            "that filename can't be used — letters, digits, dot, dash and "
            "underscore only, and no directories")
    if len(blob) > MAX_BYTES:
        raise ValueError(f"that image is {len(blob) // 1048576} MB; the limit is "
                         f"{MAX_BYTES // 1048576} MB")
    if not blob:
        raise ValueError("that file is empty")

    kind = sniff(blob[:16])
    if not kind:
        raise ValueError(
            "that isn't a PNG, JPEG, GIF or WEBP. SVG is refused on purpose: "
            "it can carry script, and the map is served from the app's own origin")

    if os.path.isfile(os.path.join(BUNDLED_DIR, safe)):
        raise ValueError(f"'{safe}' is the name of a render built into the Atlas — "
                         f"pick another, or the built-in one would always win")

    os.makedirs(settings.MAPS_DIR, exist_ok=True)
    path = os.path.join(settings.MAPS_DIR, safe)
    write_bytes_atomic(path, blob)          # never a half-written backdrop, never a lost one
    log.info("map art %s stored (%s, %d bytes)", safe, kind, len(blob))
    return safe


def remove(name):
    """Delete an uploaded render. Bundled art is not deletable."""
    safe = safe_name(name)
    if not safe:
        raise ValueError("no such render")
    if os.path.isfile(os.path.join(BUNDLED_DIR, safe)):
        raise ValueError(f"'{safe}' is built into the Atlas and can't be deleted")
    path = os.path.join(settings.MAPS_DIR, safe)
    if not os.path.isfile(path):
        raise ValueError(f"'{safe}' isn't stored here")
    os.remove(path)
    log.info("map art %s removed", safe)
