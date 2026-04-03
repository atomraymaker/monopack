import app.hidden
import importlib


module_name = "app.hidden.runtime_dep"
_runtime_dep = importlib.import_module(module_name)


def lambda_handler(event, context):
    return {
        "statusCode": 200,
        "body": _runtime_dep.message(),
    }
