from app.users.service import build_payload


def lambda_handler(event, context):
    return {
        "statusCode": 200,
        "body": build_payload(),
    }
