from app.users.service import version_payload


def lambda_handler(event, context):
    return {
        "statusCode": 200,
        "body": version_payload(),
    }
