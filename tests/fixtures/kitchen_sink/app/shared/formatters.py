def format_payload(user_id: str, token: str, version: str) -> dict[str, str]:
    return {
        "user_id": user_id,
        "token": token,
        "requests": version,
    }
