import importlib


module_name = "requests"
requests = importlib.import_module(module_name)


def lambda_handler(event, context):
    return {
        "statusCode": 200,
        "body": requests.__version__,
    }
