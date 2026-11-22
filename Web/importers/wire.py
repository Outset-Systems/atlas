TIMEOUT = 6


class Refused(Exception):
    pass


def ok(resp, who):
    if resp.status_code in (401, 403):
        raise Refused(f"{who} refused the credential.")
    if 300 <= resp.status_code < 400:
        raise Refused(f"{who} redirected to {resp.headers.get('Location', 'somewhere else')}. "
                      "Use the final URL.")
    resp.raise_for_status()
    return resp


def plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"
