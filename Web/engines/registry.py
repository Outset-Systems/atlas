from engines.checks import ChecksAdapter, _checks_adapter
from engines.deception import DeceptionAdapter, _deception_adapter
from engines.demo import DemoFeedAdapter
from engines.kuma import KumaAdapter, _kuma_adapter
from engines.prometheus import PrometheusAdapter, _prometheus_adapter
from engines.relay import RelayAdapter
from engines.static import StaticFileAdapter
from engines.unifi import UniFiAdapter, _unifi_adapter

PLACE, SERVICE, CONTAINER, STONE = "place", "service", "container", "stone"
KINDS = (PLACE, SERVICE, CONTAINER, STONE)


class Source:

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


REGISTRY = (
    Source("kuma", "Kuma", KumaAdapter, _kuma_adapter, (PLACE, SERVICE),
           needs="ATLAS_KUMA_URL", rank=1),
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
    return _BY_NAME.get(name)


def listed():
    return tuple(sorted((s for s in REGISTRY if s.listed),
                        key=lambda s: (s.rank is None, s.rank or 0)))


def listed_names():
    return tuple(s.name for s in listed())


def needs():
    return {s.name: s.needs for s in REGISTRY if s.needs}


def builders():
    return {s.name: s.build for s in REGISTRY if s.listed and not s.handed}


def default_order():
    return [s.name for s in sorted((s for s in REGISTRY if s.rank is not None),
                                   key=lambda s: s.rank)]


def label_of(name):
    source = _BY_NAME.get(name)
    return source.label if source else name
