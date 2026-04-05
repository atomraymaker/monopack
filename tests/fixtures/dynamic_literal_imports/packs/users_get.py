import importlib


runtime_dep = importlib.import_module("app.hidden.runtime_dep")
idna = __import__("idna")


def lambda_handler(event, context):
    return {
        "statusCode": 200,
        "body": f"{runtime_dep.message()}:{idna.__version__}",
    }
