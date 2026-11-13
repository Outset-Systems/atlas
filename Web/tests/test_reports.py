"""The combined security report: what the two text helpers return.

`_temperature` reads one line of state from the 24-hour block of the second
report; `_fold_weekly` drops the weekly report's sections that the second
report already covers. These tests pin what both return today, quirks
included, so the code can move between modules without changing an answer.
All report text here is invented.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import reports as subject  # noqa: E402


def _insight(day_body, after="## Last 7 days\n\nnothing of note\n"):
    return "# Insight\n\n## Last 24 hours\n" + day_body + after


def _counts(*counts):
    rows = "".join(f"{n:>5} example/scenario-{i}\n" for i, n in enumerate(counts))
    return "\n### Alerts by scenario\n\n```\n" + rows + "```\n\n"


# ── _temperature ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", [None, ""])
def test_temperature_without_a_report_is_unread(text):
    assert subject._temperature(text) == "UNREAD — no CrowdSec scroll to take it from"


def test_temperature_without_a_24_hour_heading_is_unread():
    text = "# Insight\n\n## Last 7 days\n\nnothing of note\n"
    assert subject._temperature(text) == "UNREAD — the scroll shows no 24-hour window"


def test_temperature_needs_a_heading_after_the_24_hour_block():
    """The block is read up to the NEXT `## ` heading; when it is the last
    section of the file there is no such heading and the answer is unread."""
    text = _insight(_counts(3), after="")
    assert subject._temperature(text) == "UNREAD — the scroll shows no 24-hour window"


def test_temperature_quiet_day():
    text = _insight("\n_No alerts in this window._\n\n")
    assert subject._temperature(text) == "CALM — a quiet sea (0 alerts in 24h)"


def test_temperature_quiet_marker_wins_over_a_count_block():
    text = _insight("\n_No alerts in this window._\n" + _counts(40))
    assert subject._temperature(text) == "CALM — a quiet sea (0 alerts in 24h)"


def test_temperature_without_a_scenario_block_is_unread():
    text = _insight("\nsome prose and no table\n\n")
    assert subject._temperature(text) == "UNREAD — the scroll gave no scenario count"


def test_temperature_an_empty_scenario_block_counts_zero():
    text = _insight("\n### Alerts by scenario\n\n```\n```\n\n")
    assert subject._temperature(text) == "CALM — a quiet sea (0 alerts in 24h)"


@pytest.mark.parametrize("counts,expected", [
    ((1,), "USUAL — the routine rattle (1 alert in 24h)"),
    ((2,), "USUAL — the routine rattle (2 alerts in 24h)"),
    ((10, 20), "USUAL — the routine rattle (30 alerts in 24h)"),
    ((31,), "BRISK — more knocking than usual (31 alerts in 24h)"),
    ((100, 50), "BRISK — more knocking than usual (150 alerts in 24h)"),
    ((151,), "STORM — a campaign at the gate (151 alerts in 24h)"),
    ((4000, 12), "STORM — a campaign at the gate (4012 alerts in 24h)"),
])
def test_temperature_bands(counts, expected):
    assert subject._temperature(_insight(_counts(*counts))) == expected


def test_temperature_counts_only_lines_that_open_with_a_number():
    block = ("\n### Alerts by scenario\n\n```\n"
             "    7 example/first\n"
             "example/no-count 9\n"
             "   12 example/second\n"
             "```\n\n")
    assert subject._temperature(_insight(block)) == "USUAL — the routine rattle (19 alerts in 24h)"


def test_temperature_reads_only_the_24_hour_block():
    text = _insight(_counts(5), after="## Last 7 days\n" + _counts(900))
    assert subject._temperature(text) == "USUAL — the routine rattle (5 alerts in 24h)"


# ── _fold_weekly ─────────────────────────────────────────────────────────────

def test_fold_keeps_a_report_with_no_matching_heading_whole():
    text = "preamble\n\n# Weekly\n\nbody\n\n## Certificates\n\nall fine\n\n\n"
    assert subject._fold_weekly(text) == "preamble\n\n# Weekly\n\nbody\n\n## Certificates\n\nall fine"


def test_fold_drops_one_matching_section_and_says_so():
    text = ("# Weekly\n\nintro\n\n"
            "## CrowdSec summary\n\nrepeated\n\n"
            "## Certificates\n\nall fine\n")
    assert subject._fold_weekly(text) == (
        "# Weekly\n\nintro\n\n"
        "## Certificates\n\nall fine"
        "\n_(1 edge section folded away — "
        "the CrowdSec insight above speaks for the edge.)_\n")


def test_fold_counts_every_dropped_section():
    text = ("# Weekly\n\n"
            "## Edge attack surface\n\na\n\n"
            "## Certificates\n\nb\n\n"
            "### Attack-surface detail\n\nc\n\n"
            "## crowdsec decisions\n\nd\n")
    assert subject._fold_weekly(text) == (
        "# Weekly\n\n"
        "## Certificates\n\nb"
        "\n_(3 edge sections folded away — "
        "the CrowdSec insight above speaks for the edge.)_\n")


def test_fold_keeps_a_sub_heading_under_a_dropped_heading():
    """Every `#`, `##` or `###` line starts its own part, so a sub-section
    whose own heading does not match stays although its parent went."""
    text = ("## CrowdSec\n\ngone\n\n"
            "### Hosts\n\nkept\n")
    assert subject._fold_weekly(text) == (
        "### Hosts\n\nkept"
        "\n_(1 edge section folded away — "
        "the CrowdSec insight above speaks for the edge.)_\n")


def test_fold_does_not_split_on_a_fourth_level_heading():
    text = ("## Certificates\n\nfine\n\n"
            "#### crowdsec note\n\nstays with its section\n")
    assert subject._fold_weekly(text) == (
        "## Certificates\n\nfine\n\n"
        "#### crowdsec note\n\nstays with its section")


def test_fold_matches_the_heading_line_only():
    text = "## Certificates\n\nthe crowdsec bouncer renewed its own\n"
    assert subject._fold_weekly(text) == "## Certificates\n\nthe crowdsec bouncer renewed its own"


def test_fold_keeps_the_preamble_even_when_it_names_the_subject():
    text = "crowdsec is covered elsewhere\n\n## Attack surface\n\ngone\n"
    assert subject._fold_weekly(text) == (
        "crowdsec is covered elsewhere"
        "\n_(1 edge section folded away — "
        "the CrowdSec insight above speaks for the edge.)_\n")


def test_fold_of_a_report_that_is_all_matching_sections():
    text = "# CrowdSec\n\nall of it\n"
    assert subject._fold_weekly(text) == (
        "\n_(1 edge section folded away — "
        "the CrowdSec insight above speaks for the edge.)_\n")
