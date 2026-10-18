"""Every .rt-* class a scene writes has a rule in atlas.css (v1.47.1).

v1.45.0 deleted the .rt-head / .rt-alarm / .rt-calm / .rt-waiting rules with
THE RITES, while SEALS, THE DECOYS, ACCOUNTS and THE TRUST kept emitting
them: from 2026-09-07 their summary heads were unstyled and an alarm never
turned red. Nothing failed — a class with no rule is silent — so this pins it.
"""
import pathlib
import re

WEB = pathlib.Path(__file__).resolve().parent.parent
CSS = (WEB / "static" / "atlas.css").read_text(encoding="utf-8")


def _used_rt_classes():
    used = set()
    sources = list((WEB / "static" / "js").rglob("*.js")) + [WEB / "templates" / "index.html"]
    for p in sources:
        text = p.read_text(encoding="utf-8")
        for attr in re.findall(r'class="([^"$]*)"', text):
            used.update(c for c in attr.split() if c.startswith("rt-"))
    return used


def test_scenes_still_use_rt_classes():
    assert {"rt-head", "rt-alarm", "rt-calm", "rt-waiting"} <= _used_rt_classes()


def test_every_rt_class_a_scene_writes_is_styled():
    missing = sorted(c for c in _used_rt_classes()
                     if not re.search(r"\." + re.escape(c) + r"\b[^{]*\{", CSS))
    assert not missing, f"no rule in atlas.css for: {missing}"


def test_an_alarm_is_red():
    rule = re.search(r"\.rt-alarm\s*\{([^}]*)\}", CSS)
    assert rule and "--sem-down" in rule.group(1)
