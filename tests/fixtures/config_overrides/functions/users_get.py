# monopack-start
# extra_modules: app.hidden.runtime_dep
# extra_distributions: PyYAML
# monopack-end

import importlib


def lambda_handler(event, context):
    runtime_dep = importlib.import_module("app.hidden.runtime_dep")
    return {
        "statusCode": 200,
        "body": runtime_dep.message(),
    }
