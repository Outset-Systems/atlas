STORED = ("url", "secret")
TYPES = ("url", "secret-name", "text", "select")
SECRET_IN = ("header", "path", "none")


def url_field(placeholder):
    return {"name": "url", "type": "url", "required": True,
            "label": "alerts_f_url", "text": "Address", "placeholder": placeholder}


SECRET_FIELD = {
    "name": "secret", "type": "secret-name", "required": False,
    "label": "alerts_f_secret", "text": "Secret's name",
    "hint": "alerts_secret_hint",
    "hint_text": ("The server reads ATLAS_ALERT_SECRET_<NAME> or its _FILE; "
                  "Atlas never stores the secret."),
    "placeholder": "NTFY_LAB",
}


def add_secret(headers, use, secret):
    if secret and use.get("in") == "header":
        headers[use["header"]] = f"{use.get('prefix', '')}{secret}"
    return headers
