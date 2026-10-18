"""The versioned API packages.

`api.v2` is the strangler-fig layer being grown beside the existing routes
(`api_data`, `api_admin`, `api_v1`, `api_whois`, `ingest`, `auth_routes`).
Nothing here replaces those modules until `the API migration plan` says a group has
proven parity; see that file for the order and the rules.
"""
