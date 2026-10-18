"""THE REAL-WORLD SURVEY — an isometric render of real buildings, as a backdrop.

An admin types an address or a zip code into THE CARTOGRAPHER'S TABLE; this
module geocodes it, pulls the surrounding building footprints and roads from
OpenStreetMap, extrudes the buildings, and paints an isometric block-city in
the sand table's own warm palette. The result is stored through `mapart.save`
like any uploaded render, so it appears in the gallery and can be chosen as
the map's backdrop — real geography under the fantasy chrome.

Outbound discipline (the /api/whois lesson, applied from the start):

  * Exactly TWO hosts, fixed here, never from the request: Nominatim for
    geocoding and Overpass for the data. The caller's query is a search
    STRING; it never becomes a URL, a host, or a path.
  * Timeouts and byte caps on both calls; one survey at a time (a lock), and
    the route is admin + write gated, so this cannot be driven anonymously.
  * Failures come back as one plain sentence; details go to the log.

Nominatim's usage policy wants an identifying User-Agent and no hammering —
one geocode per survey, admin-triggered, is comfortably inside it.

Rendering is pure Pillow (`pillow` in requirements, imported lazily so the
rest of the app never pays for it): local-meter projection around the geocode
point, painter's-algorithm isometric extrusion, warm greys on sand per
the design notes — SimCity, not Google Earth, and honestly so.
"""

import io
import json
import logging
import math
import re
import threading
import urllib.parse
import urllib.request

import settings

log = logging.getLogger("atlas.data.worldsurvey")

NOMINATIM = "https://nominatim.openstreetmap.org/search"
OVERPASS = "https://overpass-api.de/api/interpreter"
USER_AGENT = f"atlas/{settings.APP_VERSION} (+https://outset.systems)"

TIMEOUT_S = 15
MAX_BYTES = 8 * 1024 * 1024     # Overpass JSON for ~400 m of city is ~1–2 MB
RADIUS_M = 380                  # the neighbourhood, not the county
CANVAS = 2048                   # the same square the bundled renders use
MAX_ELEMENTS = 4000             # Overpass element cap — a dense downtown, capped
DEFAULT_HEIGHT_M = 8.0          # two storeys, when OSM says nothing
LEVEL_M = 3.2                   # metres per building:levels level

# one survey at a time — Overpass and Nominatim are shared public services,
# and two admins racing would just paint the same neighbourhood twice
_survey_lock = threading.Lock()

# a literal SPACE, not \s — \s admits newlines and tabs, and $ forgives a
# trailing newline; an address is one line. (Found when the refactor moved the
# error-wrap into _fetch and a test that "passed" turned out to be watching
# the old blanket except eat its own sentinel.)
_QUERY_OK = re.compile(r"^[\w .,#'/&()-]{2,120}\Z", re.UNICODE)


class SurveyError(ValueError):
    """A sentence fit for the settings panel; the log carries the details."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse every 3xx. The two upstream hosts are constants (Nominatim,
    Overpass); the default opener would FOLLOW a redirect from either, and a
    hostile or compromised upstream could 302 this fetch at an internal host —
    the referral-SSRF class the /api/whois fix closed, reached here through a
    redirect instead of a `refer:` line. A survey never needs to leave the two
    hosts it was pointed at, so a redirect IS the anomaly (the security review, 2026-08-16)."""
    def redirect_request(self, *a, **k):
        return None   # urllib raises HTTPError → caught below → one sentence out


# built once: no redirects, and no proxy/env openers we did not ask for
_OPENER = urllib.request.build_opener(_NoRedirect)


def _fetch(url, fail, data=None):
    """One upstream call; any transport/parse failure becomes `fail`, one
    sentence for the panel, with the details in the log (the whois idiom —
    stated once here instead of wrapped at every call site)."""
    req = urllib.request.Request(url, data=data, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })
    try:
        with _OPENER.open(req, timeout=TIMEOUT_S) as resp:
            blob = resp.read(MAX_BYTES + 1)
        if len(blob) > MAX_BYTES:
            raise SurveyError("the survey came back larger than expected — "
                              "try a more specific address")
        return json.loads(blob.decode("utf-8"))
    except SurveyError:
        raise
    except Exception as e:                       # noqa: BLE001 — one sentence out
        log.warning("survey: %s failed: %s", url.split("?")[0], e)
        raise SurveyError(fail)


def geocode(query):
    """One Nominatim lookup: (lat, lon, display_name)."""
    q = (query or "").strip()
    if not _QUERY_OK.match(q):
        raise SurveyError("give an address or a zip code — letters, digits "
                          "and ordinary punctuation")
    url = NOMINATIM + "?" + urllib.parse.urlencode(
        {"q": q, "format": "jsonv2", "limit": 1})
    rows = _fetch(url, "the gazetteer would not answer — try again shortly")
    if not rows:
        raise SurveyError(f"nowhere called {q!r} could be found")
    row = rows[0]
    return float(row["lat"]), float(row["lon"]), row.get("display_name", q)


def fetch_osm(lat, lon, radius=RADIUS_M):
    """Buildings and roads around a point, from Overpass."""
    ql = (f"[out:json][timeout:{TIMEOUT_S - 2}];"
          f"(way[\"building\"](around:{radius},{lat},{lon});"
          f"way[\"highway\"](around:{radius},{lat},{lon}););"
          f"out geom {MAX_ELEMENTS};")
    return _fetch(OVERPASS,
                  "the surveyors' guild would not answer — try again shortly",
                  data=urllib.parse.urlencode({"data": ql}).encode())


def _height_of(tags):
    """Metres of building, from whichever tag OSM actually has."""
    raw = (tags.get("height") or "").split(";")[0].strip().rstrip("m").strip()
    try:
        h = float(raw)
        if h > 0:
            return min(h, 160.0)
    except ValueError:
        pass
    try:
        levels = float(tags.get("building:levels", ""))
        if levels > 0:
            return min(levels * LEVEL_M, 160.0)
    except ValueError:
        pass
    return DEFAULT_HEIGHT_M


def parse_elements(overpass_json, lat, lon):
    """Overpass elements → local-metre geometry.

    Returns (buildings, roads): buildings as (points, height_m) with points in
    metres east/north of the survey point; roads as point lists. Pure — this
    is the half the tests exercise without any network.
    """
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(lat))

    def local(pt):
        return ((pt["lon"] - lon) * m_per_deg_lon,
                (pt["lat"] - lat) * m_per_deg_lat)

    buildings, roads = [], []
    for el in overpass_json.get("elements", []):
        geom = el.get("geometry") or []
        if len(geom) < 2:
            continue
        tags = el.get("tags") or {}
        pts = [local(p) for p in geom]
        if "building" in tags:
            if len(pts) >= 3:
                buildings.append((pts, _height_of(tags)))
        elif "highway" in tags:
            roads.append(pts)
    return buildings, roads


# ── The isometric painter ────────────────────────────────────────────────────

# the sand table's own inkpot (the design notes): warm ground, warm grey masonry —
# no neutral #888 anywhere, or the blocks read faintly blue on the sand
GROUND = (216, 196, 154)
ROAD = (196, 175, 133)
ROOF = (205, 193, 172)
WALL_LIT = (176, 162, 140)
WALL_SHADE = (140, 126, 105)
EDGE = (96, 85, 66)

_ISO_CX, _ISO_CY = math.cos(math.radians(30)), math.sin(math.radians(30))


def _iso(x, y, z=0.0):
    """metres → isometric canvas-space (unscaled)."""
    return ((x - y) * _ISO_CX, (x + y) * _ISO_CY - z)


def render_iso(buildings, roads, canvas=CANVAS):
    """Paint the block-city. Returns PNG bytes.

    Painter's algorithm: buildings sorted far→near by their nearest ground
    corner; within one building the walls go up before the roof, walls
    themselves far→near. Lighting is fixed — west faces lit, south shaded —
    which is all a block-city needs to read as volume.
    """
    from PIL import Image, ImageDraw   # lazy: only a survey pays for Pillow

    # Fit the camera to what was actually FOUND, not to the search radius: a
    # zip's centroid can land at the sparse edge of its own polygon, and a
    # fixed span then paints a sheet of empty sand with cabins in one corner.
    # Clamped so one lone shed cannot become a skyscraper-sized close-up.
    xs = [x for pts, _h in buildings for x, _y in pts]
    ys = [y for pts, _h in buildings for _x, y in pts]
    if xs:
        extent = max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
        cx = (max(xs) + min(xs)) / 2
        cy = (max(ys) + min(ys)) / 2
    else:
        extent, cx, cy = RADIUS_M * 2.0, 0.0, 0.0
    span = min(max(extent * 1.3, 180.0), RADIUS_M * 2.4)
    scale = canvas / span
    half = canvas / 2

    def cast(x, y, z=0.0):
        # the recentre rides in here rather than rebuilding every point list
        ix, iy = _iso(x - cx, y - cy, z)
        return (half + ix * scale, half * 1.08 + iy * scale)

    img = Image.new("RGB", (canvas, canvas), GROUND)
    draw = ImageDraw.Draw(img)

    for pts in roads:
        if len(pts) >= 2:
            draw.line([cast(x, y) for x, y in pts],
                      fill=ROAD, width=max(2, int(6 * scale)))

    def depth(b):
        pts, _h = b
        return min(x + y for x, y in pts)

    for pts, h in sorted(buildings, key=depth):
        base = [cast(x, y) for x, y in pts]
        top = [cast(x, y, h) for x, y in pts]
        # walls: one quad per footprint edge, far edges first
        edges = list(range(len(pts)))
        edges.sort(key=lambda i: (pts[i][0] + pts[i][1] +
                                  pts[(i + 1) % len(pts)][0] +
                                  pts[(i + 1) % len(pts)][1]))
        for i in edges:
            j = (i + 1) % len(pts)
            # face normal decides lit vs shaded — the sign of the edge's turn
            dx = pts[j][0] - pts[i][0]
            dy = pts[j][1] - pts[i][1]
            fill = WALL_LIT if dx - dy >= 0 else WALL_SHADE
            draw.polygon([base[i], base[j], top[j], top[i]],
                         fill=fill, outline=EDGE)
        draw.polygon(top, fill=ROOF, outline=EDGE)

    out = io.BytesIO()
    # default compression: `optimize=True` spent seconds per survey trying
    # every filter strategy for a marginal size win on a stored-once artifact
    img.save(out, format="PNG")
    return out.getvalue()


def survey(query):
    """The whole journey: query → stored render name.

    Serialized — one survey at a time. Returns (stored_name, display_name).
    """
    if not _survey_lock.acquire(blocking=False):
        raise SurveyError("a survey is already underway — let it finish")
    query = (query or "").strip()
    try:
        lat, lon, display = geocode(query)
        data = fetch_osm(lat, lon)
        buildings, roads = parse_elements(data, lat, lon)
        if not buildings:
            raise SurveyError(f"no charted buildings near {display!r} — OSM "
                              "has nothing to extrude there")
        png = render_iso(buildings, roads)
        slug = re.sub(r"[^A-Za-z0-9]+", "-", query).strip("-").lower()[:40]
        import mapart
        name = mapart.save(f"survey-{slug or 'somewhere'}.png", png)
        log.info("survey: %r → %s (%d buildings, %d roads)",
                 display, name, len(buildings), len(roads))
        return name, display
    finally:
        _survey_lock.release()
