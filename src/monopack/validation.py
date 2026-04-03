"""CLI-level validation helpers for inputs and option combinations."""

import re
from pathlib import Path


_FUNCTION_NAME_RE = re.compile(r"^[a-zA-Z0-9_]+$")


def validate_cli_paths(
    functions_dir: Path,
    build_dir: Path,
    project_root: Path,
    mode: str,
    with_tests: bool,
) -> None:
    """Validate required directories/files and path safety constraints."""

    if not functions_dir.exists():
        raise FileNotFoundError(
            f"Functions directory does not exist: {functions_dir}"
        )
    if not functions_dir.is_dir():
        raise ValueError(
            f"Functions directory is not a directory: {functions_dir}"
        )

    resolved_functions_dir = functions_dir.resolve()
    resolved_build_dir = build_dir.resolve()
    if resolved_build_dir == resolved_functions_dir:
        raise ValueError(
            "Build directory must be different from functions directory "
            f"(both are {functions_dir})"
        )
    if resolved_functions_dir in resolved_build_dir.parents:
        raise ValueError(
            "Build directory must not be inside functions directory: "
            f"build_dir={build_dir}, functions_dir={functions_dir}"
        )

    requirements_path = project_root / "requirements.txt"
    if not requirements_path.exists():
        raise FileNotFoundError(
            "Missing required requirements file at "
            f"{requirements_path}. Add a project-level requirements.txt."
        )
    if not requirements_path.is_file():
        raise FileNotFoundError(
            f"requirements.txt is not a file: {requirements_path}"
        )

    if mode == "test" or with_tests:
        tests_dir = project_root / "tests"
        if not tests_dir.exists() or not tests_dir.is_dir():
            raise FileNotFoundError(
                "This build configuration requires a project tests directory at "
                f"{tests_dir}. Create it or disable test execution."
            )


def validate_cli_mode_options(
    *,
    mode: str,
    with_tests: bool,
) -> None:
    """Validate mode-specific option combinations."""

    if mode not in {"deploy", "test"}:
        raise ValueError(
            f"Invalid mode '{mode}': expected 'deploy' or 'test'."
        )

    if with_tests and mode != "deploy":
        raise ValueError(
            "--with-tests is only valid with --mode deploy. "
            "Use --mode deploy or remove --with-tests."
        )


def validate_function_name(function_name: str, *, is_target: bool) -> None:
    """Validate discovered or explicitly requested function names."""

    if is_target and (
        "/" in function_name or "\\" in function_name or "." in function_name
    ):
        raise ValueError(
            "Target function name must not contain path separators or dots; "
            "use a bare function name like 'users_get'."
        )

    if _FUNCTION_NAME_RE.fullmatch(function_name) is None:
        raise ValueError(
            f"Invalid function name '{function_name}': only letters, numbers, "
            "and underscores are allowed."
        )
