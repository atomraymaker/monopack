import app.handlers.user_handler


def lambda_handler(event, context):
    return {
        "statusCode": 200,
        "body": app.handlers.user_handler.handle(),
    }
