from app.reports.generator import run_report


def lambda_handler(event, context):
    return {
        "statusCode": 200,
        "body": run_report(),
    }
