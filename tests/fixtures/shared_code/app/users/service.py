import app.shared.auth


def get_user():
    return app.shared.auth.current_user()
