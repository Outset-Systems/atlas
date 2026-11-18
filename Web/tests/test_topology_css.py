"""TOPOLOGY's drawing can be taken out of the page (2026-11-17).

The view draws ONE <svg class="tp-canvas">, cards included, so that a later
stage can write that drawing to a file with its styles in it. That only works
if nothing inside the drawing leans on the page: every rule that styles the
drawing is in `topology-canvas.css`, every one of its selectors starts with
`svg.tp-canvas`, and it reads only the `--tp-*` values that `topology.css`
sets on `svg.tp-canvas` (mapped there from the theme's tokens, so they follow
the colour scheme). An export then needs that one file and the resolved
`--tp-*` values, and nothing else. These tests hold that line, and the one
that keeps HTML out of the drawing.
"""

import pathlib
import re

WEB = pathlib.Path(__file__).resolve().parent.parent
STATIC = WEB / "static"
CANVAS_CSS = STATIC / "topology-canvas.css"
VIEW_CSS = STATIC / "topology.css"
INDEX = WEB / "templates" / "index.html"
JS = sorted((STATIC / "js").glob("topology*.js"))


def _read(p):
    return p.read_text(encoding="utf-8")


def _strip_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _rules(css):
    """(selector, body) for every innermost rule, inside @media blocks too."""
    css = _strip_comments(css)
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        yield " ".join(m.group(1).split()), m.group(2)


def _parts(selector):
    out, depth, cur = [], 0, ""
    for ch in selector:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    out.append(cur.strip())
    return [p for p in out if p]


def test_every_canvas_selector_starts_with_the_svg():
    rules = list(_rules(_read(CANVAS_CSS)))
    assert len(rules) > 20, "topology-canvas.css lost its rules"
    for sel, _ in rules:
        for part in _parts(sel):
            assert part.startswith("svg.tp-canvas"), f"a canvas rule reaches outside the drawing: {part}"


def test_the_canvas_reads_only_tp_values_and_sets_none():
    css = _strip_comments(_read(CANVAS_CSS))
    used = set(re.findall(r"var\(\s*(--[\w-]+)", css))
    assert used, "the canvas reads no values at all"
    bad = sorted(v for v in used if not v.startswith("--tp-"))
    assert not bad, f"the canvas reads page tokens it cannot carry out: {bad}"
    assert not re.search(r"(^|[;{\s])--[\w-]+\s*:", css), "a value is defined in the canvas file; they belong on svg.tp-canvas in topology.css"


def test_the_canvas_has_no_literal_colour_or_page_dependence():
    css = _strip_comments(_read(CANVAS_CSS))
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css), "a literal hex colour in the drawing"
    assert not re.search(r"\b(rgb|rgba|hsl|hsla|color-mix)\(", css), "a literal colour function in the drawing"
    assert "currentColor" not in css and "currentcolor" not in css.lower(), "currentColor follows the page"
    assert not re.search(r":\s*inherit\b", css), "inherit follows the page"
    assert not re.search(r"\d(r?em)\b", css), "rem and em follow the page's font size: use px"


def test_every_tp_value_the_canvas_reads_is_set_on_the_svg():
    used = set(re.findall(r"var\(\s*(--tp-[\w-]+)", _strip_comments(_read(CANVAS_CSS))))
    defined = {}
    for sel, body in _rules(_read(VIEW_CSS)):
        for name, value in re.findall(r"(--tp-[\w-]+)\s*:\s*([^;]+)", body):
            defined.setdefault(name, []).append((sel, value.strip()))
    missing = sorted(used - set(defined))
    assert not missing, f"the canvas reads values topology.css never sets: {missing}"
    for name, places in defined.items():
        for sel, value in places:
            assert all(p.endswith("svg.tp-canvas") for p in _parts(sel)), (
                f"{name} is set on {sel}; set it on svg.tp-canvas, where an export reads it")
            literal = re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(", value)
            assert not literal or "var(--" in value, f"{name}: {value} is a literal, not the theme's token"


def test_the_page_links_both_sheets_and_the_view():
    html = _read(INDEX)
    assert 'href="static/topology.css?v={{ v }}"' in html
    assert 'href="static/topology-canvas.css?v={{ v }}"' in html
    assert 'id="view-topology" data-view="topology"' in html
    assert 'id="topology-sheet"' in html
    for where in (r'<nav class="view-strip".*?</nav>', r'<div class="view-menu".*?</div>'):
        block = re.search(where, html, re.S)
        assert block and 'data-view="topology"' in block.group(0), f"TOPOLOGY is missing from {where[:20]}"


def test_the_drawing_holds_no_html():
    assert {p.name for p in JS} >= {"topology.js", "topology-canvas.js", "topology-panel.js",
                                    "topology-state.js", "topology-model.js"}
    for p in JS:
        text = _read(p)
        assert "foreignObject" not in text, f"{p.name} puts HTML inside the drawing"
    canvas = _read(STATIC / "js" / "topology-canvas.js")
    assert canvas.count("createElementNS(SVG, 'svg')") == 1, "the canvas is one svg"


WRITE_WORDS = ("postJSON", "WRITE_HEADERS", "admin/ops", "method: 'POST'", 'method: "POST"',
               "Editor.apply", "editor/store")


def test_only_the_drawing_writes_and_only_through_its_two_doors():
    """Drawing (2026-11-17) is the one part of the view that writes, and only
    two ways: the layout through its own route (`postJSON(LAYOUT, ...)`,
    LAYOUT being `api/v2/topology/layout`), and the map through the editor's
    store (`Editor.apply`, which carries the stamp, undo and the change log).
    It sends nothing else, and every other part of the view sends nothing."""
    draw = STATIC / "js" / "topology-draw.js"
    assert draw in JS
    for p in JS:
        if p == draw:
            continue
        text = _read(p)
        for word in WRITE_WORDS:
            assert word not in text, f"{p.name} writes ({word})"
    text = _read(draw)
    code = re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)
    assert "const LAYOUT = 'api/v2/topology/layout';" in code
    assert "from './editor/store.js'" in code
    for word in ("WRITE_HEADERS", "admin/ops", "method:", "XMLHttpRequest", "sendBeacon"):
        assert word not in code, f"topology-draw.js writes some other way ({word})"
    posts = re.findall(r"postJSON\(\s*([^,\s)]+)", code)
    assert posts and set(posts) == {"LAYOUT"}, f"postJSON to somewhere else: {posts}"
    fetches = re.findall(r"\bfetch\(\s*([^,\s)]+)", code)
    assert set(fetches) <= {"LAYOUT"}, f"fetch of something else: {fetches}"
    calls = set(re.findall(r"\bEditor\.(\w+)\(", code))
    assert calls <= {"apply", "load", "reload", "section", "writable"}, \
        f"the store is used for more than one batch of ops: {calls}"
    # and only for an admin on a wide screen: every tool is offered behind mayDraw()
    assert "if (!mayDraw())" in code and "export const mayDraw" in _read(STATIC / "js" / "topology-state.js")


def test_escape_under_a_scene_is_the_scenes():
    """A scene (TOPOLOGY in the band, RACKS, any of them) opens over this view.
    With the keyboard on the body, the view's three window Escapes once ran
    first: the light, the drawing's form or the chain's note went, and the
    scene stayed open (walked 2026-11-17). Each steps aside while a scene is
    open, so the one Escape closes the scene and nothing under it changes."""
    for name in ("topology.js", "topology-draw.js", "topology-diagnose.js"):
        code = re.sub(r"/\*.*?\*/|//[^\n]*", "", _read(STATIC / "js" / name), flags=re.S)
        guards = re.findall(r"if \(e\.key !== 'Escape' \|\| !T\.up[^\n]*\) return;", code)
        assert len(guards) == 1, f"{name}: expected one window Escape, found {len(guards)}"
        assert "|| A.sceneOpen ||" in guards[0], f"{name}: its Escape runs under an open scene"
    # Ctrl+F is the fourth key the view takes on the window: the same rule
    conductor = re.sub(r"/\*.*?\*/|//[^\n]*", "", _read(STATIC / "js" / "topology.js"), flags=re.S)
    find = re.findall(r"if \(!T\.up[^\n]*!== 'f'\) return;", conductor)
    assert len(find) == 1 and "|| A.sceneOpen ||" in find[0], "Ctrl+F reaches the find box under an open scene"
    # and those four are every key the view listens for on the window
    for name in ("topology.js", "topology-draw.js", "topology-diagnose.js"):
        code = re.sub(r"/\*.*?\*/|//[^\n]*", "", _read(STATIC / "js" / name), flags=re.S)
        on_window = re.findall(r"(?<![\w.])addEventListener\('keydown', \(e\) => \{\n\s*if \(([^\n]*)\) return;", code)
        assert on_window and all("A.sceneOpen" in guard for guard in on_window), f"{name}: a window key runs under a scene"
    assert "A.sceneOpen = name !== 'atlas';" in _read(STATIC / "js" / "ui.js")
