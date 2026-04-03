import app.users.service


def lambda_handler(event, context):
    user = app.users.service.get_user()
    return {
        "statusCode": 200,
        "body": user,
    }
