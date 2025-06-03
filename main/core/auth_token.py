import secrets


def get_token():
    return secrets.token_urlsafe(32)
