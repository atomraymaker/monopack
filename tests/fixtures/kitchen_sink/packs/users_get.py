# monopack-start
# extra_modules: app.shared.runtime_flags
# extra_distributions: 
# monopack-end

import importlib

from app.users.service import build_user_payload


def lambda_handler(event, context):
    runtime_flags = importlib.import_module("app.shared.runtime_flags")
    payload = build_user_payload()
    payload["feature"] = runtime_flags.feature_name()
    return {
        "statusCode": 200,
        "body": payload,
    }
