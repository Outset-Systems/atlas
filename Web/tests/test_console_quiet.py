"""Two console errors seen through the Hub door (2026-11-19), and what keeps
them gone.

1. The sign-in page declared its four faces in its own <style> with
   `url('/static/fonts/…')`. Behind the Hub, Atlas lives under /atlas/ and the
   Hub rewrites only src/href/action ATTRIBUTES, so those asked the Hub's own
   /static/: two answered 404 on every sign-in. The page now links
   static/fonts.css (an attribute, rewritten; its files named relative to it).
2. A place's or a service's ⋯ menu read `GET api/v2/checks/<key>` for every
   thing, and a thing with no check of its own answers that with a 404 (by
   design: "no such check" looks the same for unknown, hidden and unchecked).
   The menu now reads only what the map gives a check Atlas keeps an answer
   for.
"""

import pathlib
import re

WEB = pathlib.Path(__file__).resolve().parent.parent
LOGIN = WEB / "templates" / "login.html"
FONTS = WEB / "static" / "fonts.css"
MENU = WEB / "static" / "js" / "nodes-menu.js"


def _read(p):
    return p.read_text(encoding="utf-8")


def _page():
    """The sign-in page without its Jinja comments, which keep the history."""
    return re.sub(r"\{#.*?#\}", "", _read(LOGIN), flags=re.S)


def test_the_sign_in_page_names_no_root_path_a_proxy_cannot_rewrite():
    page = _page()
    # no url() in the page at all: a <style> is never rewritten by the Hub
    assert not re.search(r"url\(\s*['\"]?/", page), "a url('/…') in login.html misses /atlas/ behind the Hub"
    assert "@font-face" not in page, "the faces belong in static/fonts.css, not the page's own <style>"
    # every path the page names is an attribute built by url_for
    for m in re.finditer(r"(?:src|href)=\"([^\"]*)\"", page):
        assert m.group(1).startswith("{{ url_for('static'"), m.group(1)
    assert "href=\"{{ url_for('static', filename='fonts.css') }}?v={{ v }}\"" in page


def test_the_sign_in_page_faces_are_in_fonts_css_and_on_disk():
    css = _read(FONTS)
    for family, style, weight, file in (
        ("Cinzel", "normal", "600", "Cinzel-600.woff2"),
        ("Alegreya Sans", "normal", "400", "AlegreyaSans-400.woff2"),
        ("IM Fell English", "italic", "400", "IMFellEnglish-400i.woff2"),
        ("JetBrains Mono", "normal", "400", "JetBrainsMono-400.woff2"),
    ):
        rule = re.search(r"@font-face \{ font-family: '" + re.escape(family) + r"'; font-style: " + style
                         + r"; font-weight: " + weight + r";[^}]*url\('fonts/" + re.escape(file) + r"'\)", css)
        assert rule, f"{family} {style} {weight} is not in fonts.css as fonts/{file}"
        assert (WEB / "static" / "fonts" / file).is_file(), file


def test_the_preloads_ask_the_url_fonts_css_asks():
    """A preload whose URL differs from the one the face asks (a `?v` on one
    side only) fetches the file twice."""
    page = _page()
    pre = re.findall(r'<link rel="preload" as="font"[^>]*href="([^"]*)"', page, re.S)
    assert len(pre) == 2
    for href in pre:
        assert "?v" not in href and "filename='fonts/" in href, href


def test_a_menu_reads_a_check_only_where_there_is_one():
    js = _read(MENU)
    body = re.search(r"function hasCheck\(kind, id\) \{.*?\n\}", js, re.S)
    assert body, "hasCheck is gone"
    assert "M.checkAsk(kind, A.DATA, id, { unmanaged }) === true" in body.group(0)
    open_menu = re.search(r"export async function openMenu\(.*?\n\}", js, re.S).group(0)
    assert "if (hasCheck(kind, id) && !freshRead(id)) reads.push(readCheck(id));" in open_menu
    # and nothing else reads one behind its back
    assert js.count("readCheck(") == 2, "a second caller of readCheck: gate it with hasCheck too"
