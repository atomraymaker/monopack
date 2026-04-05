from app.users import service


def lambda_handler(event, context):
    return {
        "statusCode": 200,
        "body": service.build_payload(),
    }
