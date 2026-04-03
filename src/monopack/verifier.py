import subprocess
import sys
from pathlib import Path


def verifier_script_source(function_name: str, selected_modules: set[str]) -> str:
    imports = [f"import {module}" for module in sorted(selected_modules)]
    imports.append(f"import functions.{function_name} as target")
    imports.append("assert hasattr(target, 'lambda_handler'), 'lambda_handler is missing'")
    return "\n".join(imports) + "\n"


def write_verifier_script(path: Path, function_name: str, selected_modules: set[str]) -> None:
    path.write_text(
        verifier_script_source(function_name, selected_modules),
        encoding="utf-8",
    )


def run_verifier_script(script_path: Path, cwd: Path) -> None:
    completed = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if completed.returncode == 0:
        return

    raise RuntimeError(
        "Build verification failed. "
        f"stdout:\n{completed.stdout}\n"
        f"stderr:\n{completed.stderr}"
    )


def run_unittest_discovery(tests_dir: Path, cwd: Path) -> None:
    try:
        start_dir = tests_dir.relative_to(cwd).as_posix()
    except ValueError:
        start_dir = str(tests_dir)

    completed = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", start_dir, "-v"],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if completed.returncode == 0:
        return

    raise RuntimeError(
        "Test discovery failed. "
        f"stdout:\n{completed.stdout}\n"
        f"stderr:\n{completed.stderr}"
    )
