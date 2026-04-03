from ..services import users


def handle():
    return users.get_user()
