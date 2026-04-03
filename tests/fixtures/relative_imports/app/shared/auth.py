from .tokens import current_token


def current_user(user_id):
    return f"{user_id}:{current_token()}"
