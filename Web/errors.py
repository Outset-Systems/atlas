from flask import jsonify


def fail(status, error, *, reason=None, problems=None, **extra):
    body = dict(extra)
    body["error"] = error
    if reason is not None:
        body["reason"] = reason
    if problems is not None:
        body["problems"] = problems
    return jsonify(body), status
