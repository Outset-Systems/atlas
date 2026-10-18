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

import logging
import mimetypes
import os
import re

import settings
from jsonio import write_bytes_atomic

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


def available():
    """Every base render this Atlas could be pointed at, bundled first."""
    out = []
    foreign = _theme.foreign_maps()       # another theme's set: kept, not offered
    for directory, bundled in ((BUNDLED_DIR, True), (settings.MAPS_DIR, False)):
        try:
            names = sorted(os.listdir(directory))
        except OSError:
            continue
        for name in names:
            path = os.path.join(directory, name)
            if not safe_name(name) or not os.path.isfile(path):
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
