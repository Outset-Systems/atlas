import os

import settings

REPORTS = {"security": "security-report.md"}


def _read_report(key):
    path = os.path.join(settings.REPORTS_DIR, REPORTS[key])
    try:
        with open(path, encoding="utf-8-sig") as fh:
            return fh.read(), os.path.getmtime(path)
    except OSError:
        return None, None


def _security_scroll():
    body, _ = _read_report("security")
    return body or "_No security report has been delivered yet._"
