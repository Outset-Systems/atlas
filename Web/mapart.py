import json
import logging
import math
import mimetypes
import os
import re

import settings
import theme as _theme
from jsonio import write_bytes_atomic, write_json_atomic

log = logging.getLogger("atlas.data.mapart")

mimetypes.add_type("image/webp", ".webp")

BUNDLED_DIR = os.path.join(settings.HERE, "static", "map")

STYLE_SUFFIX = ".style.json"
MAX_STYLE_WORDS = 40
STYLE_WORD_KEY = re.compile(r"(?:[^\W\d_]|[' ’-]){2,30}")
STYLE_WORD = re.compile(r"(?:[^\W_]|[' ’-]){1,30}")
MAX_STYLE_REGIONS = 32
MAX_STYLE_POINTS = 512
STYLE_POINT_RANGE = (-40, 140)
_REGION_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

MAX_BYTES = 24 * 1024 * 1024

SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
)

MIMETYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
}


DEFAULT = _theme.T["map_art"]

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def safe_name(name):
    name = (name or "").strip()
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return None
    if ".." in name:
        return None
    return name if _SAFE_NAME.match(name) else None


def sniff(head):
    for signature, kind in SIGNATURES:
        if head.startswith(signature):
            return kind
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


def resolve(name):
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
    return f"static/map/{name}" if bundled else f"map-art/{name}"


def read_upload(name):
    safe = safe_name(name)
    if not safe:
        return None, None
    path = os.path.join(settings.MAPS_DIR, safe)
    if not os.path.isfile(path):
        return None, None
    try:
        with open(path, "rb") as handle:
            blob = handle.read()
    except OSError:
        return None, None
    return blob, sniff(blob[:16])


def _style_points(raw):
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


ICONS_DIR = os.path.join(settings.HERE, "static", "icons")
_ICON_SLUG = _theme.SLUG_RE


def _style_logos(raw):
    if not isinstance(raw, dict):
        return {}
    out = {}
    for key, slug in list(raw.items())[:MAX_STYLE_POINTS]:
        if (_REGION_ID.match(str(key)) and isinstance(slug, str) and _ICON_SLUG.match(slug)
                and os.path.isfile(os.path.join(ICONS_DIR, slug + ".svg"))):
            out[key] = slug
    return out


def _style_region(raw):
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
        region["fold"] = True
    if raw.get("hidden") is True:
        region["hidden"] = True
    pins = _style_points(raw.get("places"))
    if pins:
        region["places"] = pins
    return region


def _style_words(raw):
    if not isinstance(raw, dict):
        return {}
    out = {}
    for key, value in list(raw.items())[:MAX_STYLE_WORDS]:
        key = str(key).strip().lower()
        if isinstance(value, str) and STYLE_WORD_KEY.fullmatch(key) and STYLE_WORD.fullmatch(value.strip()):
            out[key] = value.strip()
    return out


def _sidecar_name(render):
    return render.rsplit(".", 1)[0] + STYLE_SUFFIX


class _NotAnObject(ValueError):
    pass


def _read_sidecar(path):
    with open(path, encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        raise _NotAnObject("not an object")
    return raw


def style(name):
    safe = safe_name(name)
    if not safe:
        return {}
    filename = _sidecar_name(safe)
    for directory in (BUNDLED_DIR, settings.MAPS_DIR):
        path = os.path.join(directory, filename)
        if not os.path.isfile(path):
            continue
        try:
            raw = _read_sidecar(path)
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
    safe = safe_name(name)
    path, bundled = resolve(safe) if safe else (None, False)
    if not path:
        raise ValueError("no such map image")
    filename = _sidecar_name(safe)
    if bundled or os.path.isfile(os.path.join(BUNDLED_DIR, filename)):
        raise ValueError("this map style is built into the Atlas, so its layout is part of the image")
    if not isinstance(body, dict):
        raise ValueError("expected an object of places, zones and regions")
    target = os.path.join(settings.MAPS_DIR, filename)
    from filelock import exclusive, lock_for
    with exclusive(lock_for(target)):
        return _merge_layout(target, filename, body)


def _merge_layout(target, filename, body):
    raw = {}
    if os.path.isfile(target):
        try:
            raw = _read_sidecar(target)
        except _NotAnObject:
            raise ValueError(f"the sidecar {filename} is not an object, so it was left alone") from None
        except (OSError, ValueError) as e:
            raise ValueError(f"the sidecar {filename} cannot be read, so it was left alone: {e}") from e
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
    try:
        names = os.listdir(directory)
    except OSError:
        return set()
    return {region["map"]
            for name in names if name.endswith(STYLE_SUFFIX)
            for region in style(name[:-len(STYLE_SUFFIX)] + ".webp").get("regions", [])}


def available():
    out = []
    foreign = _theme.foreign_maps()
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
                continue
            out.append({"name": name, "bundled": bundled,
                        "bytes": os.path.getsize(path)})
    return out


def save(name, blob):
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

    path = os.path.join(settings.MAPS_DIR, safe)
    write_bytes_atomic(path, blob)
    log.info("map art %s stored (%s, %d bytes)", safe, kind, len(blob))
    return safe


def remove(name):
    safe = safe_name(name)
    if not safe:
        raise ValueError("no such render")
    if os.path.isfile(os.path.join(BUNDLED_DIR, safe)):
        raise ValueError(f"'{safe}' is built into the Atlas and can't be deleted")
    path = os.path.join(settings.MAPS_DIR, safe)
    if not os.path.isfile(path):
        raise ValueError(f"'{safe}' isn't stored here")
    os.remove(path)
    sidecar = os.path.join(settings.MAPS_DIR, _sidecar_name(safe))
    if os.path.isfile(sidecar):
        os.remove(sidecar)
    log.info("map art %s removed", safe)
