from app.shared.auth import build_token


def build_payload():
    return build_token()
