import requests

from ..shared.auth import token_for
from ..shared.formatters import format_payload


def build_user_payload() -> dict[str, str]:
    return format_payload("42", token_for("users"), requests.__version__)
