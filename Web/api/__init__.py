"""The HTTP API packages.

`api.v2` is the API: one blueprint at `/api/v2/` carrying every read, write,
feed and probe. `api.status` serves the two unversioned paths: `/api/status`
(the card contract dashboards and uptime monitors probe), from the same
builder as `/api/v2/health`, and `/api/manifest` (the app manifest, at the
address the Hub reads), from the same builder as `/api/v2/manifest`. The pages
are not an API and live in `views.py` and `auth_routes.py`.
"""
