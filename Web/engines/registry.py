"""The registry: every status source, declared once (2026-11-16).

What a source is used to be spread over three lists that had to agree by
hand: the builders in `signals`, and the names and the settings they need in
`integrations`. Each source has one entry here, and those three lists are
read from it (`builders`, `listed_names`, `needs`).

This module keeps the rule of the package: at load it imports only the
standard library and other `engines` modules, because a relay box runs it
with no web stack beside it. Nothing here imports `integrations`, `settings`,
`signals` or `watch`.
"""

from engines.checks import ChecksAdapter, _checks_adapter
from engines.deception import DeceptionAdapter, _deception_adapter
from engines.demo import DemoFeedAdapter
from engines.kuma import KumaAdapter, _kuma_adapter
from engines.prometheus import PrometheusAdapter, _prometheus_adapter
from engines.relay import RelayAdapter
from engines.static import StaticFileAdapter
from engines.unifi import UniFiAdapter, _unifi_adapter

#: The kinds of thing a source can give a state for. A `container` is kept
#: for a source that asks the container's own system: none does today, and a
#: container link's state is its service's (a monitor, or a check of its
#: address).
PLACE, SERVICE, CONTAINER, STONE = "place", "service", "container", "stone"
KINDS = (PLACE, SERVICE, CONTAINER, STONE)


class Source:
    """One status source, as it declares itself.

    name         what the operator lists, and what the feed calls it
    label        the word NODES shows under "Watched by" (the page keeps its
                 own copy, `nodes_by_<name>`; a test holds the two together)
    needs        the setting that must be set before it can be switched on,
                 or None
    answers_for  which of KINDS it can give a state for, read from what its
                 adapter returns: `nodes` is a place, `services` a service,
                 `stones` a stone
    rank         its place in the order offered to a new install
                 (`default_order`), or None for a source that is not offered
    adapter      its adapter class
    build        how it is built: called with the value of `needs`, or with
                 what the hub hands a source that needs none (the feed file
                 for `static`, the site for `relay`, nothing for `checks`).
                 Returns the adapter, or None when it cannot be built. None
                 for `demo`, which the hub adds by itself
    listed       whether an operator may name it in the list of sources
    handed       True for a source that serves a feed handed to Atlas (a
                 file, a relay's push) and asks nothing itself
    guarded      True for a source whose failed build is skipped (said in the
                 log) instead of raised: only unifi (2026-11-17)
    """

    __slots__ = ("name", "label", "needs", "answers_for", "rank", "adapter", "build",
                 "listed", "handed", "guarded")

    def __init__(self, name, label, adapter, build, answers_for, needs=None, rank=None,
                 listed=True, handed=False, guarded=False):
        self.name = name
        self.label = label
        self.needs = needs
        self.answers_for = tuple(answers_for)
        self.rank = rank
        self.adapter = adapter
        self.build = build
        self.listed = listed
        self.handed = handed
        self.guarded = guarded

    def __repr__(self):
        return f"<Source {self.name}>"


#: Every source. The order of the entries is the order `needs` and `builders`
#: are read in, which is the order a save checks the settings in: keep it.
#: The ranks follow the rule for who is believed: the monitor the owner named
#: first (kuma), the connected systems next (prometheus, unifi), Atlas's own
#: checks after them. The decoy feed comes last because it answers for
#: nothing the others do. A relay's push and a feed file are an operator's
#: own arrangement and are not offered to a new install.
REGISTRY = (
    Source("kuma", "Kuma", KumaAdapter, _kuma_adapter, (PLACE, SERVICE),
           needs="ATLAS_KUMA_URL", rank=1),
    # numbers only (the plaque counts, the patch survey): it sets no state
    Source("prometheus", "Prometheus", PrometheusAdapter, _prometheus_adapter, (),
           needs="ATLAS_PROM_URL", rank=2),
    Source("deception", "Decoy feed", DeceptionAdapter, _deception_adapter, (STONE,),
           needs="ATLAS_DECOYS_URL", rank=5),
    Source("unifi", "UniFi", UniFiAdapter, _unifi_adapter, (PLACE,),
           needs="ATLAS_UNIFI_URL", rank=3, guarded=True),
    Source("checks", "Atlas", ChecksAdapter, _checks_adapter, (PLACE, SERVICE), rank=4),
    Source("relay", "Relay", RelayAdapter, RelayAdapter, (PLACE, SERVICE, STONE),
           handed=True),
    Source("static", "A file", StaticFileAdapter, StaticFileAdapter, (PLACE, SERVICE, STONE),
           handed=True),
    Source("demo", "Demo", DemoFeedAdapter, None, (PLACE, SERVICE, STONE),
           listed=False, handed=True),
)

_BY_NAME = {source.name: source for source in REGISTRY}


def find(name):
    """The entry for a source name, or None."""
    return _BY_NAME.get(name)


def listed():
    """The sources an operator may name, in the order the settings offer
    them: the ranked ones by rank, then the rest as they were added."""
    return tuple(sorted((s for s in REGISTRY if s.listed),
                        key=lambda s: (s.rank is None, s.rank or 0)))


def listed_names():
    """The names an operator may list (`integrations.SOURCES`)."""
    return tuple(s.name for s in listed())


def needs():
    """{source: the setting that must be set before it can be switched on},
    for the sources that need one (`integrations.SOURCE_NEEDS`)."""
    return {s.name: s.needs for s in REGISTRY if s.needs}


def builders():
    """{source: its builder} for the listed sources that ask a system
    themselves (`signals._BUILDERS`)."""
    return {s.name: s.build for s in REGISTRY if s.listed and not s.handed}


def default_order():
    """The order offered to a new install: the ranked sources, by rank. It is
    an offer only. The order the operator lists is the one that counts."""
    return [s.name for s in sorted((s for s in REGISTRY if s.rank is not None),
                                   key=lambda s: s.rank)]


def label_of(name):
    """The word shown for a source under "Watched by"; the name itself for
    one the registry does not know."""
    source = _BY_NAME.get(name)
    return source.label if source else name
