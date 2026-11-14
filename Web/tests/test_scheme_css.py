"""THE LIGHT SCHEME's contract (v1.52.0, the design notes 2026-10-19), and the bar
that follows the map (stage 1, 2026-11-13).

Panels follow the scheme. The light values are restated only on the panel
containers, so these tests pin four things a future edit could quietly break:
every token the light block restates exists in the night palette (no orphan
spelling), the constant tokens never flip, no panel rule goes back to a literal
colour that should flip, and every text token clears WCAG AA (4.5:1) on every
ground it sits on, in BOTH schemes, computed from the token values themselves.

The bar (10-20's list) has a block of its own, on a four-way condition that is
evaluated here for all 24 cases. The table is a night map under every pick;
the Sky's and the Depths' grounds swap on a pick, as two token sets whose
copies must stay identical.
"""
import pathlib
import re

WEB = pathlib.Path(__file__).resolve().parent.parent
CSS = WEB / "static" / "atlas.css"
DESK = WEB / "static" / "desk.css"
INDEX = WEB / "templates" / "index.html"
BOOT = WEB / "static" / "js" / "atlas.js"

LIGHT_SEL = ':root[data-scheme="light"] :is('
#: the bar block's head: its first clause
BAR_SEL = ':root[data-scheme-pick="light"] :is('
#: the panels: what follows the scheme
PANELS = ["#index-drawer", ".ldg-panel", ".trb-panel", ".rel-panel", ".pth-panel",
          ".pal-panel", ".gl-panel", ".dsk-panel", ".wiz-panel", "#view-nodes",
          # OVERVIEW's tiles (2026-11-13 stage 3): the tiles' sheet, not the whole
          # view, because the Depths' section lifted below them reads `--surface`
          # and `--ink-line` and must keep its dark ground
          "#overview-tiles",
          # ALERTS (2026-11-13 stage 4): one sheet, so the whole view, as NODES
          "#view-alerts"]
#: the bar: 10-20's list; the chart pop-ups and arrows go with it
BAR = ["#scenes-list", ".scene-home", ".chrome", ".rl-crumbs", ".rl-locator", ".rl-hint",
       ".chron-fly-pop", ".chron-arrow", ".embed-max-arrow", "#embed-max-close",
       # the views' menu, ATLAS's ▾ and the phone's strip (2026-11-13)
       "#view-menu", ".view-strip", ".scene-more"]
#: the bar and what draws inside it: none of these may key on `data-scheme`
BAR_RE = re.compile(r"#scenes-list|\.scene\b|\.scene-home|\.band-|\.chrome\b|\.ci-|#btn-|"
                    r"\.view-tool|\.vt-lamp|\.menu-tools|\.rl-crumbs?|\.rl-locator|\.rl-hint|\.rl-here|"
                    r"\.rl-sep|\.chron-fly-pop|\.chron-arrow|\.embed-max-arrow|#embed-max-close|\.sch-|"
                    r"#view-menu|\.view-menu|\.view-strip|\.scene-more")
#: the bar's own fills: night on :root, light in the bar block
BAR_TOKENS = ["--bar-glass", "--bar-glass-firm", "--bar-shadow-firm", "--chrome-glass",
              "--chrome-glass-firm", "--crumb-glass", "--crumb-shadow", "--hint-glass",
              "--hint-shadow", "--pop-shadow", "--scene-shadow", "--scene-active-bg",
              "--sky-lit-fill", "--sky-lit-ink", "--sky-lit-border", "--depths-lit-fill",
              "--depths-lit-ink", "--depths-lit-border", "--bar-sun", "--bar-moon",
              "--hover-glow-a"]
#: tokens the light block must restate, or a panel keeps a night value
MUST_FLIP = ["--abyss", "--surface", "--surface-2", "--ink-line", "--ink-soft", "--text",
             "--text-dim", "--text-soft", "--gilt", "--gilt-bright", "--gilt-rgb", "--on-gilt",
             "--sem-up", "--sem-warn", "--sem-down", "--sem-info", "--down-rgb", "--tone-up",
             "--tone-warn", "--tone-down", "--tone-info", "--shade-rgb", "--shade-k", "--hair",
             "--frame-ground"]
#: tokens that are the same in both schemes (the parchment card, the CTA, the Depths)
CONSTANT = ["--parchment", "--parchment-dim", "--card-ink", "--card-ink-soft", "--discover",
            "--discover-hover", "--depth", "--depth-rgb"]
#: the chrome that floats over the map follows the scheme too (2026-10-20:
#: "themes should also change the colour of all the flyouts")
CHROME = ["#scenes-list", ".chrome", ".rl-crumbs", ".rl-locator", ".rl-hint", ".chron-fly-pop"]
#: map-side containers: never under the light selector
NIGHT = ["#stage", "#viewport", "#veil", "#card", "#toast",
         "#colophon", "#drift-note", "#region-lens", ".rg-tab", ".mk-sat"]


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


def _bar_palettes():
    css = _strip_comments(_read(CSS))
    _, root = _block(css, ":root {")
    sel, bar = _block(css, BAR_SEL)
    return _decls(root), _decls(bar), sel


def _bar(name):
    root, bar, _ = _bar_palettes()
    return _resolved(dict(root) if name == "dark" else {**root, **bar})


_VAR = re.compile(r"var\(\s*(--[\w-]+)\s*(?:,\s*([^()]*(?:\([^()]*\)[^()]*)*))?\)")


def _subst(value, scope, depth=0):
    """Resolve var() the way a browser does for one element: from `scope`."""
    assert depth < 12, f"var() loop at {value}"

    def one(m):
        name, fb = m.group(1), m.group(2)
        if name in scope and scope[name] != "initial":
            return _subst(scope[name], scope, depth + 1)
        assert fb is not None, f"{name} is not defined here and has no fallback"
        return _subst(fb, scope, depth + 1)
    return _VAR.sub(one, value)


def _resolved(scope):
    return {k: _subst(v, scope) for k, v in scope.items()}


def _hex(value):
    """A hex colour, or an opaque rgb()/rgba() written out as hex."""
    v = value.strip()
    if v.startswith("#"):
        return v
    m = re.fullmatch(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+))?\s*\)", v)
    assert m and (m.group(4) is None or float(m.group(4)) == 1), f"not an opaque colour: {value}"
    return "#" + "".join(f"{int(m.group(i)):02x}" for i in (1, 2, 3))


def _over(rgba, ground):
    """`rgba(r, g, b, a)` composited over the hex `ground`."""
    m = re.fullmatch(r"rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([\d.]+)\s*\)", rgba.strip())
    assert m, f"not an rgba(): {rgba}"
    a = float(m.group(4))
    g = ground.lstrip("#")
    under = [int(g[i:i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(f"{round(int(m.group(i + 1)) * a + u * (1 - a)):02x}" for i, u in enumerate(under))


def test_the_light_block_restates_every_panel_token_and_invents_none():
    root, light, _ = _palettes()
    missing = [t for t in MUST_FLIP if t not in light]
    assert not missing, f"the light block does not restate {missing}: those panels keep night values"
    orphans = [t for t in light if t not in root]
    assert not orphans, f"the light block defines {orphans}, which the night palette does not: a typo, or a token with no dark value"


def test_the_bar_block_restates_every_token_and_invents_none():
    root, bar, _ = _bar_palettes()
    missing = [t for t in MUST_FLIP + BAR_TOKENS if t not in bar]
    assert not missing, f"the bar block does not restate {missing}: a light bar keeps night values"
    orphans = [t for t in bar if t not in root]
    assert not orphans, f"the bar block defines {orphans}, which :root does not"
    _, light, _ = _palettes()
    differ = [t for t in MUST_FLIP if light[t] != bar[t]]
    assert not differ, f"the bar and the panels are the same light scheme, but {differ} differ"


def test_the_constant_tokens_never_flip():
    _, light, _ = _palettes()
    _, bar, _ = _bar_palettes()
    flipped = [t for t in CONSTANT if t in light or t in bar]
    assert not flipped, f"{flipped} are the same in both schemes (parchment card, CTA, the Depths)"


def _names(sel, items):
    return [i for i in items if re.search(re.escape(i) + r"(?![\w-])", sel)]


def test_the_light_selector_names_the_panels_and_no_map_side_container():
    _, _, sel = _palettes()
    html = _read(INDEX)
    for p in PANELS:
        assert p in sel, f"{p} is a panel but is not under the light selector"
        name = p.lstrip("#.")
        attr = "id" if p.startswith("#") else "class"
        assert re.search(rf'{attr}="[^"]*\b{re.escape(name)}\b', html) or p in (".dsk-panel", ".wiz-panel"), (
            f"{p} is under the light selector but the page has no such element")
    assert not _names(sel, BAR), f"{_names(sel, BAR)} are the bar: they follow the map, not the OS"
    for n in NIGHT:
        assert n not in sel, f"{n} is map-side: the map is a night map in both schemes"


def test_the_bar_block_names_the_bar_and_no_panel():
    _, _, sel = _bar_palettes()
    clauses = _clauses(sel)
    assert len(clauses) == 4, f"the bar's condition is four clauses, spelt once (got {len(clauses)})"
    for clause in clauses:
        for b in BAR:
            assert re.search(re.escape(b) + r"(?![\w-])", clause), f"{b} is missing from a bar clause: {clause[:90]}"
    for c in CHROME:
        assert c in sel, f"{c} floats over the map and should follow the bar"
    assert not _names(sel, PANELS), f"{_names(sel, PANELS)} are panels: they follow the OS or the pick"
    for n in NIGHT:
        assert n not in sel, f"{n} is map-side: the map is a night map under every pick"


# ── the bar's condition, evaluated ──────────────────────────────────────────

def _split_top(text):
    """Split on commas outside parentheses."""
    out, depth, cur = [], 0, ""
    for ch in text:
        depth += ch == "("
        depth -= ch == ")"
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    out.append(cur.strip())
    return out


def _clauses(sel):
    return _split_top(" ".join(sel.split()))


def _match_clause(clause, html_attrs, body):
    """`:root[attr="v"]… [body<compound>] :is(BAR)`, against <html>'s attributes
    and <body>'s classes. Only the shapes the bar block uses are understood; any
    other shape fails loudly rather than guessing."""
    m = re.match(r":root((?:\[[^\]]+\])*)\s+", clause)
    assert m and clause.endswith(")"), f"a bar clause the matcher cannot read: {clause}"
    for k, v in re.findall(r'\[([\w-]+)="([^"]*)"\]', m.group(1)):
        if html_attrs.get(k) != v:
            return False
    rest = clause[m.end():]
    if not rest.startswith("body"):
        assert rest.startswith(":is("), f"a bar clause the matcher cannot read: {clause}"
        return True
    depth, end = 0, len(rest)
    for i, ch in enumerate(rest):
        depth += ch == "("
        depth -= ch == ")"
        if ch == " " and depth == 0:
            end = i
            break
    assert rest[end:].strip().startswith(":is("), f"a bar clause the matcher cannot read: {clause}"
    rest = rest[len("body"):end]
    while rest:
        t = re.match(r"\.([\w-]+)", rest)
        if t:
            if t.group(1) not in body:
                return False
            rest = rest[t.end():]
            continue
        t = re.match(r":(not|is)\(([^()]*)\)", rest)
        assert t, f"the matcher cannot read {rest!r} in {clause}"
        names = [n.strip().lstrip(".") for n in t.group(2).split(",")]
        hit = any(n in body for n in names)
        if (t.group(1) == "not" and hit) or (t.group(1) == "is" and not hit):
            return False
        rest = rest[t.end():]
    return True


#: barScheme(pick, OS, where), written out: 3 picks × 2 OS schemes × 4 places
BAR_TABLE = {
    ("auto", "light", "sky"): "light",   ("auto", "light", "depths"): "dark",
    ("auto", "light", "table"): "light", ("auto", "light", "other"): "light",
    ("auto", "dark", "sky"): "light",    ("auto", "dark", "depths"): "dark",
    ("auto", "dark", "table"): "dark",   ("auto", "dark", "other"): "dark",
    ("light", "light", "sky"): "light",  ("light", "light", "depths"): "light",
    ("light", "light", "table"): "light", ("light", "light", "other"): "light",
    ("light", "dark", "sky"): "light",   ("light", "dark", "depths"): "light",
    ("light", "dark", "table"): "light", ("light", "dark", "other"): "light",
    ("dark", "light", "sky"): "dark",    ("dark", "light", "depths"): "dark",
    ("dark", "light", "table"): "dark",  ("dark", "light", "other"): "dark",
    ("dark", "dark", "sky"): "dark",     ("dark", "dark", "depths"): "dark",
    ("dark", "dark", "table"): "dark",   ("dark", "dark", "other"): "dark",
}
#: the body classes each place can wear. 'other' is a scene, the Deck or a
#: phone, with the camera anywhere (the classes are read, never written here)
PLACES = {
    "sky": [{"in-sky"}],
    "depths": [{"depths"}],
    "table": [set()],
    "other": [{"scene-open"}, {"in-sky", "scene-open"}, {"depths", "scene-open"},
              {"deck"}, {"in-sky", "deck"}, {"depths", "deck"}, {"phone"}, {"in-sky", "phone"}],
}


def test_the_bar_condition_gives_bar_schemes_table_in_all_24_cases():
    assert len(BAR_TABLE) == 24
    _, _, sel = _bar_palettes()
    clauses = _clauses(sel)
    wrong = []
    for (pick, os_scheme, where), want in BAR_TABLE.items():
        panels = os_scheme if pick == "auto" else pick   # resolveScheme: data-scheme
        attrs = {"data-scheme-pick": pick, "data-scheme": panels}
        for body in PLACES[where]:
            got = "light" if any(_match_clause(c, attrs, body) for c in clauses) else "dark"
            if got != want:
                wrong.append(f"pick {pick}, OS {os_scheme}, {where} {sorted(body)}: bar {got}, want {want}")
    assert not wrong, "the bar's CSS disagrees with barScheme:\n" + "\n".join(wrong)


def test_no_data_scheme_rule_names_the_bar():
    """A rule keyed on `data-scheme` follows the OS while the bar follows the
    camera; only the bar block's own clauses may say `data-scheme`, beside the pick."""
    bad = []
    for path in (CSS, DESK):
        for sel, _ in _rules(_read(path)):
            for part in _split_top(sel):
                if not re.search(r"data-scheme(?!-pick)", part) or "data-scheme-pick" in part:
                    continue
                if BAR_RE.search(part) or part.strip() == ':root[data-scheme="light"]':
                    bad.append(f"{path.name}: {part[:100]}")
    assert not bad, "rules that key the bar on the OS:\n" + "\n".join(bad)


def test_the_v1584_depths_band_is_gone():
    css = _strip_comments(_read(CSS))
    assert "body.depths #scenes-list" not in css
    assert "body.depths .chrome:not(.lit)" not in css
    root, bar, _ = _bar_palettes()
    assert root["--bar-glass-firm"] == "rgba(13,11,7,0.86)"
    assert bar["--bar-glass-firm"] == "rgba(214, 218, 224, 0.94)"
    assert "background: var(--bar-glass-firm);" in re.search(
        r"^body\.scene-open #scenes-list \{.*?^\}", css, re.S | re.M).group(0)


def test_every_text_token_clears_aa_on_its_grounds_in_both_schemes():
    for name in ("dark", "light"):
        for p in (_scheme(name), _bar(name)):
            for fg in ("--text", "--text-dim", "--text-soft", "--gilt"):
                for ground in ("--abyss", "--surface", "--surface-2"):
                    r = _ratio(p[fg], p[ground])
                    assert r >= 4.5, f"{name}: {fg} {p[fg]} on {ground} {p[ground]} is {r:.2f}:1, under 4.5"


def test_each_lit_journey_reads_on_both_bars():
    """Being lit follows the bar's colour. The ink on the fill is text (4.5:1);
    the fill against the bar's ground is a mark (3:1)."""
    for name in ("dark", "light"):
        p = _bar(name)
        for j in ("sky", "depths"):
            fill, ink = _hex(p[f"--{j}-lit-fill"]), _hex(p[f"--{j}-lit-ink"])
            r = _ratio(ink, fill)
            assert r >= 4.5, f"{name} bar: the lit {j} ink {ink} on {fill} is {r:.2f}:1"
            r = _ratio(fill, p["--abyss"])
            assert r >= 3.0, f"{name} bar: the lit {j} fill {fill} on the bar's ground is {r:.2f}:1"
    root, bar, _ = _bar_palettes()
    assert root["--sky-lit-fill"] == "var(--gilt)" and root["--sky-lit-ink"] == "var(--on-gilt)", (
        "on a dark bar the Sky lights gilt with its own ink (plan: the card-ink fill would vanish)")
    assert bar["--depths-lit-fill"] == "#0f766e", "on a light bar the Depths light deep teal"


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


def test_the_glass_still_reads_with_black_behind_it():
    """Light panels are translucent, so the ground is not a token: composite the
    glass over the scrim over black, the worst thing a panel can sit on."""
    css = _strip_comments(_read(CSS))
    rgba = r"background: rgba\((\d+), (\d+), (\d+), ([\d.]+)\)"
    glass = re.search(r"\.wiz-panel\)\s*\{\s*" + rgba, css)
    scrim = re.search(r"#trust, #settings\)\s*\{\s*" + rgba, css)
    assert glass and scrim, "the glass rules moved, or the panels went opaque again"
    under = [int(scrim.group(i)) * float(scrim.group(4)) for i in (1, 2, 3)]
    alpha = float(glass.group(4))
    over = [int(glass.group(i)) * alpha + u * (1 - alpha) for i, u in zip((1, 2, 3), under)]
    ground = "#" + "".join(f"{round(c):02x}" for c in over)
    p = _scheme("light")
    for fg in ("--text", "--text-dim", "--text-soft", "--gilt"):
        r = _ratio(p[fg], ground)
        assert r >= 4.5, f"{fg} {p[fg]} on glass over black ({ground}) is {r:.2f}:1"


# ── the two grounds ──────────────────────────────────────────────────────────

#: the stage and section pieces that change with the ground
GROUND_RE = re.compile(r"#void\b|#void-fade|\.depths-glow|\.depths-motes|\.depths-cloud|#depths-realm|"
                       r"#depth-map-shade|#sky-realm|\.sky-glow|\.cloud-bank|\.cloud-svg|#sky-map-light|"
                       r"\.fog-[ab]|#vignette|\.depths-kin|#chronicle|#abyss|#colophon|#viewport")
#: the table: a night map under every pick
TABLE_RE = re.compile(r"#map-base|\.zone-label|\.rg-tab|#sky-island|#sky-shadow|style-bright|"
                      r"\.mk(?!\.depths-kin)(?![\w-])")


def test_the_grounds_follow_the_pick_never_the_os():
    picks = {"light": False, "dark": False}
    for sel, _ in _rules(_read(CSS)):
        for part in _split_top(sel):
            if not GROUND_RE.search(part):
                continue
            assert not re.search(r"data-scheme(?!-pick)", part), (
                f"a ground rule keyed on the OS: {part[:100]}")
            for p in picks:
                picks[p] |= f'data-scheme-pick="{p}"' in part
    assert all(picks.values()), f"no ground rule for the pick(s) {[p for p, v in picks.items() if not v]}"


def test_the_table_is_under_no_scheme_or_pick():
    bad = []
    for sel, _ in _rules(_read(CSS)):
        for part in _split_top(sel):
            if "data-scheme" in part and TABLE_RE.search(part):
                bad.append(part[:100])
    assert not bad, "the table is a night map under every pick:\n" + "\n".join(bad)


def _set_copies(marker):
    """Each rule whose body opens with the set's marker comment."""
    css = _read(CSS)
    out = []
    for m in re.finditer(r"([^{}]+)\{\s*/\* " + re.escape(marker) + r" \*/([^{}]*)\}", css):
        sel = " ".join(_strip_comments(m.group(1)).split())
        out.append((sel, [" ".join(d.split()) for d in m.group(2).split(";") if d.strip()]))
    return out


def test_each_section_set_is_the_same_in_every_copy():
    sky, depths = _set_copies("THE SKY SET"), _set_copies("THE DEPTHS SET")
    assert sorted(s for s, _ in sky) == sorted(["#chronicle", ':root[data-scheme-pick="light"] #abyss'])
    assert sorted(s for s, _ in depths) == sorted(["#abyss", ':root[data-scheme-pick="dark"] #chronicle'])
    for name, copies in (("Sky", sky), ("Depths", depths)):
        assert copies[0][1] == copies[1][1], f"the two copies of the {name} set have drifted"
    keys = lambda decls: [d.split(":", 1)[0] for d in decls]
    assert keys(sky[0][1]) == keys(depths[0][1]), "the two sets must name the same tokens, in the same order"
    for t in ("--sec-ground", "--sec-head", "--sec-head-glow", "--sec-sub", "--sec-plaque-ink",
              "--sec-plaque-bg", "--sec-plaque-border", "--sec-frame-bg", "--sec-frame-pane",
              "--sec-deck-ground", "--sec-deck-border", "--ch-1", "--ch-text", "--ch-surface"):
        assert t in keys(sky[0][1]), f"the sets do not carry {t}"


def _section_scope(section, set_marker):
    css = _strip_comments(_read(CSS))
    root = _decls(_block(css, ":root {")[1])
    hue = {}
    for m in re.finditer(r"(?m)^" + re.escape(section) + r" \{([^{}]*)\}", css):
        d = _decls(m.group(1))
        if "--hue-rgb" in d:
            hue = d
    assert hue, f"{section} declares no hue"
    sset = dict(d.split(":", 1) for d in _set_copies(set_marker)[0][1])
    sset = {k.strip(): v.strip() for k, v in sset.items()}
    return _resolved({**root, **hue, **sset})


def test_each_section_reads_on_its_ground_under_every_pick():
    """Heading (26px: 3:1), sub-line and plaques (4.5:1), for both sections on
    both grounds, measured on the set's worst field (`--sec-ground`). The plaque
    is measured on its own wash over that field."""
    for section in ("#chronicle", "#abyss"):
        for marker in ("THE SKY SET", "THE DEPTHS SET"):
            p = _section_scope(section, marker)
            ground = _hex(p["--sec-ground"])
            where = f"{section} on {marker.split()[1].lower()} ground"
            r = _ratio(_hex(p["--sec-head"]), ground)
            assert r >= 3.0, f"{where}: the heading {p['--sec-head']} is {r:.2f}:1"
            r = _ratio(_hex(p["--sec-sub"]), ground)
            assert r >= 4.5, f"{where}: the sub-line {p['--sec-sub']} is {r:.2f}:1"
            for ink, wash in (("--sec-plaque-ink", "--sec-plaque-bg"), ("--sec-plaque-hot", "--sec-plaque-bg-hot")):
                under = _over(p[wash], ground)
                r = _ratio(_hex(p[ink]), under)
                assert r >= 4.5, f"{where}: the plaque {ink} {p[ink]} on {under} is {r:.2f}:1"


def test_the_depths_pins_read_on_paper():
    css = _strip_comments(_read(CSS))
    core = re.search(r':root\[data-scheme-pick="light"\] body\.depths \.mk\.depths-kin \.mk-core \{\s*'
                     r"background: (#[0-9a-fA-F]{6});", css)
    assert core, "under Light the lit pins have no core of their own"
    ground = _hex(_section_scope("#abyss", "THE SKY SET")["--sec-ground"])
    r = _ratio(core.group(1), ground)
    assert r >= 3.0, f"the deep teal core {core.group(1)} on paper is {r:.2f}:1"


def test_the_colour_change_is_instant_under_reduced_motion():
    """Every bar element that gained a 400ms colour transition is named in the
    one reduced-motion block, and that block names nothing else."""
    css = _strip_comments(_read(CSS))
    moved = set()
    for sel, body in _rules(css):
        if re.search(r"transition:[^;]*\b(?:background-color|color|border-color) 400ms", body):
            moved |= {p for p in _split_top(sel) if BAR_RE.search(p) or p.startswith(".chron-fly-pop")}
    m = re.search(r"@media \(prefers-reduced-motion: reduce\) \{\s*([^{}]+)\{ transition-duration: 0s; \}", css)
    assert m, "no reduced-motion block for the bar's colour change"
    named = set(_split_top(" ".join(m.group(1).split())))
    assert moved, "nothing gained the colour transition"
    assert moved == named, f"transitioned but not stilled: {moved - named}; stilled but never moved: {named - moved}"


def test_the_light_accent_is_blue():
    p = _scheme("light")
    r, g, b = [int(p["--gilt"].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    assert b > r and b > g, "the light scheme's accent is blue, not amber"
    light_rules = [l for l in _read(CSS).splitlines() if 'data-scheme="light"' in l]
    assert not [l for l in light_rules if "251, 241, 199" in l], "a warm ground survived in the light rules"
