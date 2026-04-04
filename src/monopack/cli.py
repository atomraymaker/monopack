import argparse
import io
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr
import sys

from monopack import __version__
from monopack.build import build_function, prewarm_shared_build_state
from monopack.discovery import discover_functions
from monopack.validation import (
    validate_cli_mode_options,
    validate_cli_paths,
    validate_function_name,
)


def _parse_env_bool(var_name: str, default: bool) -> bool:
    raw_value = os.environ.get(var_name)
    if raw_value is None:
        return default

    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes"}:
        return True
    if normalized in {"0", "false", "no"}:
        return False

    raise ValueError(
        f"Invalid boolean value for {var_name}: {raw_value!r}. "
        "Expected one of: 1, 0, true, false, yes, no."
    )


def _parse_env_mode() -> str:
    return os.environ.get("MONOPACK_MODE", "deploy")


def _parse_jobs(raw_value: str) -> int | str:
    normalized = raw_value.strip().lower()
    if normalized == "auto":
        return "auto"

    try:
        parsed = int(normalized)
    except ValueError as exc:
        raise ValueError(
            f"Invalid --jobs value: {raw_value!r}. Expected a positive integer or 'auto'."
        ) from exc

    if parsed < 1:
        raise ValueError(
            f"Invalid --jobs value: {raw_value!r}. Expected a positive integer or 'auto'."
        )

    return parsed


def _default_auto_jobs(function_count: int) -> int:
    if function_count < 2:
        return 1

    cpu_count = os.cpu_count() or 1
    suggested = max(1, cpu_count - 1)
    return max(1, min(function_count, suggested, 8))


def _resolve_jobs(
    raw_value: str,
    *,
    function_count: int,
    auto_fix: bool,
    has_target: bool,
) -> int:
    parsed = _parse_jobs(raw_value)
    if has_target:
        return 1

    if isinstance(parsed, int):
        jobs = parsed
    else:
        jobs = _default_auto_jobs(function_count)
    jobs = min(max(1, jobs), function_count)

    if auto_fix and jobs > 1:
        print(
            "--auto-fix may rewrite source files; forcing --jobs=1 for safety.",
            file=sys.stderr,
        )
        return 1

    return jobs


def _parse_sha_output(raw_value: str) -> set[str]:
    values = {value.strip().lower() for value in raw_value.split(",") if value.strip()}
    if not values:
        raise ValueError(
            "Invalid --sha-output value: expected one or more comma-separated values "
            "from: hex, b64."
        )

    invalid = sorted(values - {"hex", "b64"})
    if invalid:
        raise ValueError(
            f"Unsupported --sha-output values: {', '.join(invalid)}. "
            "Supported values: b64, hex."
        )

    return values


def parse_args(argv=None):
    parser = argparse.ArgumentParser(prog="monopack")
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument("function_name", nargs="?")
    parser.add_argument(
        "--functions-dir",
        default=os.environ.get("MONOPACK_FUNCTIONS_DIR", "functions"),
    )
    parser.add_argument(
        "--build-dir",
        default=os.environ.get("MONOPACK_BUILD_DIR", "build"),
    )
    parser.add_argument(
        "--mode",
        choices=["deploy", "test"],
        default=_parse_env_mode(),
    )
    parser.add_argument("--with-tests", action="store_true")

    verify_group = parser.add_mutually_exclusive_group()
    verify_group.add_argument("--verify", dest="verify", action="store_true")
    verify_group.add_argument("--no-verify", dest="verify", action="store_false")

    parser.add_argument("--auto-fix", dest="auto_fix", action="store_true")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument(
        "--jobs",
        default=os.environ.get("MONOPACK_JOBS", "auto"),
        help="Parallel workers for multi-function builds (positive integer or 'auto').",
    )
    parser.add_argument(
        "--sha-output",
        default="hex",
        help=(
            "Comma-separated package digest outputs for deploy mode: hex,b64 "
            "(use b64 for Terraform source_code_hash workflows)"
        ),
    )

    parser.set_defaults(verify=_parse_env_bool("MONOPACK_VERIFY", True))
    parser.set_defaults(auto_fix=_parse_env_bool("MONOPACK_AUTO_FIX", False))
    parser.set_defaults(with_tests=_parse_env_bool("MONOPACK_WITH_TESTS", False))
    parser.set_defaults(debug=_parse_env_bool("MONOPACK_DEBUG", False))

    return parser.parse_args(argv)


def main(argv=None):
    try:
        args = parse_args(argv)
        functions_dir = Path(args.functions_dir)
        build_dir = Path(args.build_dir)
        project_root = functions_dir.parent
        sha_outputs = _parse_sha_output(args.sha_output)

        validate_cli_mode_options(
            mode=args.mode,
            with_tests=args.with_tests,
        )
        validate_cli_paths(
            functions_dir,
            build_dir,
            project_root,
            args.mode,
            args.with_tests,
        )

        if args.function_name is not None:
            validate_function_name(args.function_name, is_target=True)
            function_names = [args.function_name]
        else:
            function_names = discover_functions(functions_dir)
            if not function_names:
                raise RuntimeError(
                    f"No functions discovered in {functions_dir}. "
                    "Add at least one function file (*.py) or pass a target function name."
                )
            for function_name in function_names:
                validate_function_name(function_name, is_target=False)

        jobs = _resolve_jobs(
            args.jobs,
            function_count=len(function_names),
            auto_fix=args.auto_fix,
            has_target=args.function_name is not None,
        )
        shared_state = None
        if len(function_names) > 1:
            shared_state = prewarm_shared_build_state(
                project_root=project_root,
                build_dir=build_dir,
            )

        if jobs <= 1:
            for function_name in function_names:
                build_target = build_function(
                    function_name=function_name,
                    functions_dir=functions_dir,
                    build_dir=build_dir,
                    project_root=project_root,
                    verify=args.verify,
                    mode=args.mode,
                    auto_fix=args.auto_fix,
                    with_tests=args.with_tests,
                    debug=args.debug,
                    sha_outputs=sha_outputs,
                    shared_state=shared_state,
                )
                print(build_target)
        else:
            results: dict[str, tuple[Path, str]] = {}
            errors: list[tuple[str, Exception]] = []

            def _build_parallel(function_name: str) -> tuple[Path, str]:
                stderr_buffer = io.StringIO()
                with redirect_stderr(stderr_buffer):
                    build_target = build_function(
                        function_name=function_name,
                        functions_dir=functions_dir,
                        build_dir=build_dir,
                        project_root=project_root,
                        verify=args.verify,
                        mode=args.mode,
                        auto_fix=args.auto_fix,
                        with_tests=args.with_tests,
                        debug=args.debug,
                        sha_outputs=sha_outputs,
                        shared_state=shared_state,
                    )
                return build_target, stderr_buffer.getvalue()

            with ThreadPoolExecutor(max_workers=jobs) as executor:
                future_to_name = {
                    executor.submit(_build_parallel, function_name): function_name
                    for function_name in function_names
                }
                for future, function_name in future_to_name.items():
                    try:
                        results[function_name] = future.result()
                    except Exception as exc:  # pragma: no cover - exercised via CLI path
                        errors.append((function_name, exc))

            if errors:
                ordered_failures = sorted(errors, key=lambda item: item[0])
                details = "\n".join(
                    f"- {function_name}: {error}"
                    for function_name, error in ordered_failures
                )
                raise RuntimeError(
                    "One or more function builds failed:\n"
                    f"{details}"
                )

            for function_name in function_names:
                build_target, buffered_stderr = results[function_name]
                if buffered_stderr:
                    print(buffered_stderr, file=sys.stderr, end="")
                print(build_target)
    except (FileNotFoundError, KeyError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
