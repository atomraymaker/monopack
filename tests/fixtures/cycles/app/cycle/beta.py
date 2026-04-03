from app.cycle import alpha


def read_cycle():
    if alpha.__name__:
        return "ok"
    return "bad"
