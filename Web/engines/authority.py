"""Who speaks for a thing (2026-11-16): the rule, in one place.

For each watched thing one source is the authority at a time:

  1. a monitor the owner named for it (Kuma today);
  2. the connected system that owns the thing (UniFi for its device,
     Prometheus for a target it scrapes);
  3. Atlas's own check.

The rule used to be spelled out where it was applied, in two places. They
both read it from here now, and neither changed what it does:

  * `watch.targets` keeps steps 1 and 3 apart: Atlas's own check does not ask
    what a named monitor already watches (`place_check`, `service_check`),
    and a service's check answers for its place only where no monitor does
    (`rolls_up`). With the map's "Check beside Kuma" on, the check still asks
    and its answer is a shadow: counted beside the monitor's, never shown in
    its place.
  * `signals._merge` decides between the sources that did answer: the one the
    operator listed later speaks (`merge`), and only an answer that
    carries a state is credited with it (`gives_state`). That order is the
    operator's setting. `registry.default_order` is the order this rule
    suggests for a new install, and it is only an offer.

Like the rest of the package this imports nothing beyond the standard library
at load: a relay box runs it with no web stack beside it.
"""

#: What Atlas's own check of a thing is: the thing's answer, or a shadow set
#: beside a monitor's. The words are the `kind` of a watch target.
PLACE = "place"
SHADOW_PLACE = "shadow-place"
SERVICE = "service"
SHADOW = "shadow"

#: The source a monitor the owner named speaks through: step 1 above.
MONITOR = "kuma"

def place_check(monitored, shadow):
    """How Atlas's own check asks a place, or None when it does not ask.

    `monitored`: a monitor the owner named watches the place. `shadow`: the
    map has "Check beside Kuma" on. With no monitor the check is the place's
    answer. With one, the monitor speaks and the check stays quiet, unless
    shadow is on, when it asks and its answer is set beside the monitor's.
    """
    if not monitored:
        return PLACE
    return SHADOW_PLACE if shadow else None


def service_check(named, tied, shadow):
    """How Atlas's own check asks a service, or None when it does not ask.

    `named`: the service's link names a monitor. `tied`: that monitor is tied
    to a place, so it reaches the feed only folded into the place and has no
    answer of its own to set a shadow beside. `shadow`: as for a place.
    """
    if not named:
        return SERVICE
    if not shadow or tied:
        return None
    return SHADOW


def rolls_up(place_monitored, named):
    """Whether a service's check may answer for its place as well: only where
    no monitor watches the place and none is named for the service."""
    return not place_monitored and not named


def gives_state(info):
    """Whether one source's entry for a thing says what state it is in. A
    source that only adds another key to a place is not credited with its
    state ("Watched by")."""
    return isinstance(info, dict) and bool(info.get("state"))


def merge(feeds, names=None):
    """Deep-merge partial feeds. Later feeds win per-key (order = adapter priority:
    `engines/authority.py` holds the rule, 2026-11-16).

    With `names` (one adapter name per feed), the merged feed also says which
    adapter supplied each place's state: `confirmed_by` = {place id: name}
    (2026-11-13, for the places table). Only an entry that carries a `state`
    counts, so an adapter that adds another key to a place does not take the
    credit for its state. In memory only: nothing stores it.
    """
    merged = {"nodes": {}, "services": {}, "stones": {}, "metrics": {}}
    confirmed = {}
    for i, feed in enumerate(feeds):
        for nid, info in feed.get("nodes", {}).items():
            merged["nodes"].setdefault(nid, {}).update(info)
            if names is not None and gives_state(info):
                confirmed[nid] = names[i]
        for sid, info in feed.get("services", {}).items():
            merged["services"].setdefault(sid, {}).update(info)
        for tid, info in feed.get("stones", {}).items():
            merged["stones"].setdefault(tid, {}).update(info)
        merged["metrics"].update(feed.get("metrics", {}))
    if names is not None:
        merged["confirmed_by"] = confirmed
    return merged
