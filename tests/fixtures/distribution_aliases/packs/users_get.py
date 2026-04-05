import importlib


yaml_module_name = "yaml"
dateutil_module_name = "dateutil.parser"

yaml = importlib.import_module(yaml_module_name)
dateutil_parser = importlib.import_module(dateutil_module_name)


def lambda_handler(event, context):
    return {
        "statusCode": 200,
        "body": f"{yaml.__name__}:{dateutil_parser.__name__}",
    }
