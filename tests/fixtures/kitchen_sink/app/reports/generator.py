import importlib


module_name = "idna"
idna = importlib.import_module(module_name)


def run_report() -> str:
    return idna.__version__
