from . import profile
from ..shared import auth


def get_user():
    return auth.current_user(profile.USER_ID)
