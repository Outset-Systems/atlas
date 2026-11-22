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
MAX_BYTES = 8 * 1024 * 1024
RADIUS_M = 380
CANVAS = 2048
MAX_ELEMENTS = 4000
DEFAULT_HEIGHT_M = 8.0
LEVEL_M = 3.2

_survey_lock = threading.Lock()

_QUERY_OK = re.compile(r"^[\w .,#'/&()-]{2,120}\Z", re.UNICODE)


class SurveyError(ValueError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _fetch(url, fail, data=None):
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
    except Exception as e:
        log.warning("survey: %s failed: %s", url.split("?")[0], e)
        raise SurveyError(fail)


def geocode(query):
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
    ql = (f"[out:json][timeout:{TIMEOUT_S - 2}];"
          f"(way[\"building\"](around:{radius},{lat},{lon});"
          f"way[\"highway\"](around:{radius},{lat},{lon}););"
          f"out geom {MAX_ELEMENTS};")
    return _fetch(OVERPASS,
                  "the surveyors' guild would not answer — try again shortly",
                  data=urllib.parse.urlencode({"data": ql}).encode())


def _height_of(tags):
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



GROUND = (216, 196, 154)
ROAD = (196, 175, 133)
ROOF = (205, 193, 172)
WALL_LIT = (176, 162, 140)
WALL_SHADE = (140, 126, 105)
EDGE = (96, 85, 66)

_ISO_CX, _ISO_CY = math.cos(math.radians(30)), math.sin(math.radians(30))


def _iso(x, y, z=0.0):
    return ((x - y) * _ISO_CX, -(x + y) * _ISO_CY - z)


def render_iso(buildings, roads, canvas=CANVAS):
    from PIL import Image, ImageDraw

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
        return -max(x + y for x, y in pts)

    def area(pts):
        return sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
                   for i in range(len(pts))) / 2

    for pts, h in sorted(buildings, key=depth):
        base = [cast(x, y) for x, y in pts]
        top = [cast(x, y, h) for x, y in pts]
        edges = list(range(len(pts)))
        edges.sort(key=lambda i: -(pts[i][0] + pts[i][1] +
                                   pts[(i + 1) % len(pts)][0] +
                                   pts[(i + 1) % len(pts)][1]))
        outward = 1 if area(pts) >= 0 else -1
        for i in edges:
            j = (i + 1) % len(pts)
            dx = pts[j][0] - pts[i][0]
            dy = pts[j][1] - pts[i][1]
            nx, ny = dy * outward, -dx * outward
            fill = WALL_LIT if nx < ny else WALL_SHADE
            draw.polygon([base[i], base[j], top[j], top[i]],
                         fill=fill, outline=EDGE)
        draw.polygon(top, fill=ROOF, outline=EDGE)

    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def survey(query):
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
