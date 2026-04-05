from app.cycle.alpha import read_cycle


def lambda_handler(event, context):
    return {
        "statusCode": 200,
        "body": read_cycle(),
    }
