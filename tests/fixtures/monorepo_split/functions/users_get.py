from app.users.service import get_user_payload


def lambda_handler(event, context):
    return {
        "statusCode": 200,
        "body": get_user_payload(),
    }
