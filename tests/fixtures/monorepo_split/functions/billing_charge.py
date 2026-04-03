from app.billing.charge import run_charge


def lambda_handler(event, context):
    return {
        "statusCode": 200,
        "body": run_charge(),
    }
