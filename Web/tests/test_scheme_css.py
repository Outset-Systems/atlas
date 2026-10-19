"""THE LIGHT SCHEME's contract (v1.52.0, the design notes 2026-10-19).

Panels follow the scheme; the map is a night map in both. The light values are
restated only on the panel containers, so these tests pin four things a future
edit could quietly break: every token the light block restates exists in the
night palette (no orphan spelling), the constant tokens never flip, no panel
rule goes back to a literal colour that should flip, and every text token
clears WCAG AA (4.5:1) on every ground it sits on, in BOTH schemes, computed
from the token values themselves.
"""
import pathlib
import re

WEB = pathlib.Path(__file__).resolve().parent.parent
CSS = WEB / "static" / "atlas.css"
DESK = WEB / "static" / "desk.css"
INDEX = WEB / "templates" / "index.html"
BOOT = WEB / "static" / "js" / "atlas.js"

LIGHT_SEL = ':root[data-scheme="light"] :is('
#: the panels: what follows the scheme
PANELS = ["#index-drawer", ".ldg-panel", ".trb-panel", ".rel-panel", ".pth-panel",
          ".pal-panel", ".gl-panel", ".dsk-panel", ".wiz-panel"]
#: tokens the light block must restate, or a panel keeps a night value
MUST_FLIP = ["--abyss", "--surface", "--surface-2", "--ink-line", "--ink-soft", "--text",
             "--text-dim", "--text-soft", "--gilt", "--gilt-bright", "--gilt-rgb", "--on-gilt",
             "--sem-up", "--sem-warn", "--sem-down", "--sem-info", "--down-rgb", "--tone-up",
             "--tone-warn", "--tone-down", "--tone-info", "--shade-rgb", "--shade-k", "--hair",
             "--frame-ground"]
#: tokens that are the same in both schemes (the parchment card, the CTA, the Depths)
CONSTANT = ["--parchment", "--parchment-dim", "--card-ink", "--card-ink-soft", "--discover",
            "--discover-hover", "--depth", "--depth-rgb"]
#: map-side containers: never under the light selector
NIGHT = ["#stage", "#viewport", "#veil", ".chrome", "#scenes-list", "#card", "#toast",
         "#colophon", "#drift-note", "#region-lens", ".zoom-stack", ".atlas-tools"]


def _read(p):
    return p.read_text(encoding="utf-8")


def _strip_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _block(css, head):
    i = css.index(head)
    j = css.index("{", i)
    k = css.index("}", j)
    return css[i:j], css[j + 1:k]


def _decls(body):
    out = {}
    for d in body.split(";"):
        if ":" in d:
            k, v = d.split(":", 1)
            if k.strip().startswith("--"):
                out[k.strip()] = v.strip()
    return out


def _palettes():
    css = _strip_comments(_read(CSS))
    _, root = _block(css, ":root {")
    sel, light = _block(css, LIGHT_SEL)
    return _decls(root), _decls(light), sel


def _lum(hexv):
    h = hexv.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _ratio(a, b):
    la, lb = sorted([_lum(a), _lum(b)], reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _scheme(name):
    root, light, _ = _palettes()
    return dict(root) if name == "dark" else {**root, **light}


def test_the_light_block_restates_every_panel_token_and_invents_none():
    root, light, _ = _palettes()
    missing = [t for t in MUST_FLIP if t not in light]
    assert not missing, f"the light block does not restate {missing}: those panels keep night values"
    orphans = [t for t in light if t not in root]
    assert not orphans, f"the light block defines {orphans}, which the night palette does not: a typo, or a token with no dark value"


def test_the_constant_tokens_never_flip():
    _, light, _ = _palettes()
    flipped = [t for t in CONSTANT if t in light]
    assert not flipped, f"{flipped} are the same in both schemes (parchment card, CTA, the Depths)"


def test_the_light_selector_names_the_panels_and_no_map_side_container():
    _, _, sel = _palettes()
    html = _read(INDEX)
    for p in PANELS:
        assert p in sel, f"{p} is a panel but is not under the light selector"
        name = p.lstrip("#.")
        attr = "id" if p.startswith("#") else "class"
        assert re.search(rf'{attr}="[^"]*\b{re.escape(name)}\b', html) or p in (".dsk-panel", ".wiz-panel"), (
            f"{p} is under the light selector but the page has no such element")
    for n in NIGHT:
        assert n not in sel, f"{n} is map-side: the map is a night map in both schemes"


def test_every_text_token_clears_aa_on_its_grounds_in_both_schemes():
    for name in ("dark", "light"):
        p = _scheme(name)
        for fg in ("--text", "--text-dim", "--text-soft", "--gilt"):
            for ground in ("--abyss", "--surface", "--surface-2"):
                r = _ratio(p[fg], p[ground])
                assert r >= 4.5, f"{name}: {fg} {p[fg]} on {ground} {p[ground]} is {r:.2f}:1, under 4.5"


def test_the_status_hues_read_as_marks_in_both_schemes():
    """Status colours are dots, strokes and badges beside a word (the design notes):
    WCAG's non-text minimum, 3:1, on the panel grounds."""
    for name in ("dark", "light"):
        p = _scheme(name)
        for fg in ("--sem-up", "--sem-warn", "--sem-down", "--sem-info",
                   "--tone-up", "--tone-warn", "--tone-down", "--tone-info"):
            for ground in ("--surface", "--abyss"):
                r = _ratio(p[fg], p[ground])
                assert r >= 3.0, f"{name}: {fg} {p[fg]} on {ground} is {r:.2f}:1, under 3"


def test_a_label_on_a_gilt_fill_is_legible_in_both_schemes():
    for name in ("dark", "light"):
        p = _scheme(name)
        r = _ratio(p["--on-gilt"], p["--gilt"])
        assert r >= 4.5, f"{name}: --on-gilt on --gilt is {r:.2f}:1"
        # .sp-btn-go sets --abyss on a gilt fill
        r = _ratio(p["--abyss"], p["--gilt"])
        assert r >= 4.5, f"{name}: --abyss on --gilt (the GO button) is {r:.2f}:1"


#: panel rules (excluding the rack's dark-metal devices and the parchment form,
#: constant by design) must not carry the literal families the tokens replaced
_PANEL_RE = re.compile(r"(#index-drawer|\.drawer-|\.dtab|\.idx-|\.svc-|\.ldg-|\.rel-|\.trb-|\.pth-|"
                       r"\.pal-|\.gl-|\.sp-|\.dir-|\.acct-|\.rt-|\.cal-|\.ann-|\.seal|\.gs-|\.tr-|"
                       r"\.acc-|#settings-panel|\.dsk-|\.wiz-|\.rep-)")
_EXEMPT_RE = re.compile(r"(\.rel-dev|\.fp-|\.rel-niche|\.rel-gateway|\.rel-forge|\.rel-patch|\.rel-port|"
                        r"\.dsk-form|\.dsk-input|\.dsk-req|\.dsk-chip|\.dsk-subcard|\.dsk-extra|"
                        r"\.dsk-swatch|\.dsk-help|\.scene-edit|#first-survey|data-scheme)")
_FORBIDDEN = re.compile(r"rgba\(\s*0\s*,\s*0\s*,\s*0\s*,|rgba\(\s*255\s*,\s*255\s*,\s*255\s*,\s*0?\.05\s*\)|"
                        r"#(7A9B6E|C06B62|C49A52|7FB0C4|b7a983|1a1a17|101010)\b", re.I)


def _rules(css):
    css = _strip_comments(css)
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        yield " ".join(m.group(1).split()), m.group(2)


def test_no_panel_rule_keeps_a_literal_that_should_flip():
    bad = []
    for path in (CSS, DESK):
        for sel, body in _rules(_read(path)):
            if not _PANEL_RE.search(sel) or _EXEMPT_RE.search(sel):
                continue
            for decl in body.split(";"):
                if decl.strip().startswith("text-shadow"):
                    continue
                if _FORBIDDEN.search(decl):
                    bad.append(f"{path.name}: {sel[:70]} → {' '.join(decl.split())[:80]}")
    assert not bad, "panel rules with literal colours that do not flip:\n" + "\n".join(bad)


def test_the_toggle_is_in_the_band_and_boots_first():
    html = _read(INDEX)
    m = re.search(r'<span class="menu-tools" id="menu-tools">(.*?)</span>', html, re.S)
    assert m and 'id="btn-scheme"' in m.group(1), "☀/☾ is not in the ⚙ cluster"
    boot = _read(BOOT)
    imports = re.findall(r"^import (?:[^'\n]* from )?'\./([^']+)'", boot, re.M)
    assert imports[:2] == ["config.js", "scheme.js"], (
        f"scheme.js must load right after config.js (got {imports[:3]}): data-scheme "
        "has to stand before any panel can open")
