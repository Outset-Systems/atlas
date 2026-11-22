PLACE = "place"
SHADOW_PLACE = "shadow-place"
SERVICE = "service"
SHADOW = "shadow"

MONITOR = "kuma"

def place_check(monitored, shadow):
    if not monitored:
        return PLACE
    return SHADOW_PLACE if shadow else None


def service_check(named, tied, shadow):
    if not named:
        return SERVICE
    if not shadow or tied:
        return None
    return SHADOW


def rolls_up(place_monitored, named):
    return not place_monitored and not named


def gives_state(info):
    return isinstance(info, dict) and bool(info.get("state"))


def merge(feeds, names=None):
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
