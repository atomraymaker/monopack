from pathlib import Path


def discover_functions(functions_dir: Path) -> list[str]:
    return sorted(
        path.stem
        for path in functions_dir.glob("*.py")
        if path.is_file() and not path.name.startswith("_")
    )


def resolve_entrypoint(functions_dir: Path, function_name: str) -> Path:
    entrypoint = functions_dir / f"{function_name}.py"
    if entrypoint.is_file():
        return entrypoint

    raise FileNotFoundError(
        f"Function '{function_name}' not found in {functions_dir}"
    )
