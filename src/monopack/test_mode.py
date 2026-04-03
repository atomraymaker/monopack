"""Test-mode helpers for selecting and copying relevant tests."""

import shutil
from pathlib import Path

from monopack.imports import classify_roots, extract_imports_from_file
from monopack.module_resolver import module_name_from_path


def module_names_from_files(
    files: set[Path],
    project_root: Path,
    first_party_roots: set[str],
) -> set[str]:
    """Convert selected source files to importable module names."""

    modules: set[str] = set()

    for file_path in files:
        if file_path.name == "__init__.py":
            continue
        relative = file_path.relative_to(project_root)
        if not relative.parts or relative.parts[0] not in first_party_roots:
            continue
        modules.add(module_name_from_path(file_path, project_root))

    return modules


def test_file_is_relevant(test_file: Path, selected_modules: set[str]) -> bool:
    """Return True when a test imports a selected runtime module lineage."""

    if not selected_modules:
        return False

    for imported_module in extract_imports_from_file(test_file):
        for selected_module in selected_modules:
            if modules_are_related(imported_module, selected_module):
                return True

    return False


def copy_relevant_tests(
    project_root: Path,
    build_target: Path,
    selected_modules: set[str],
) -> Path | None:
    """Copy tests related to selected modules into the build target."""

    source_tests = project_root / "tests"
    if not source_tests.is_dir():
        return None

    relevant_tests = [
        path
        for path in sorted(source_tests.rglob("test*.py"))
        if test_file_is_relevant(path, selected_modules)
    ]
    if not relevant_tests:
        return None

    destination_tests = build_target / "tests"

    for source_test in relevant_tests:
        destination = destination_tests / source_test.relative_to(source_tests)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_test, destination)

    for init_file in _required_parent_init_files(relevant_tests, source_tests):
        destination = destination_tests / init_file.relative_to(source_tests)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(init_file, destination)

    return destination_tests


def modules_are_related(imported_module: str, selected_module: str) -> bool:
    """Return True when imported and selected modules overlap by ancestry."""

    return (
        imported_module == selected_module
        or imported_module.startswith(f"{selected_module}.")
        or selected_module.startswith(f"{imported_module}.")
    )


def _required_parent_init_files(test_files: list[Path], source_tests: Path) -> list[Path]:
    """Collect package ``__init__.py`` files needed for copied test imports."""

    init_files: set[Path] = set()

    for test_file in test_files:
        current = test_file.parent
        while True:
            init_file = current / "__init__.py"
            if init_file.exists():
                init_files.add(init_file)
            if current == source_tests:
                break
            current = current.parent

    return sorted(init_files)


def collect_third_party_roots_from_tests(
    tests_dir: Path,
    first_party_roots: set[str],
) -> set[str]:
    """Extract third-party import roots referenced by copied tests."""

    third_party_roots: set[str] = set()

    for path in sorted(tests_dir.rglob("*.py")):
        modules = extract_imports_from_file(path)
        _, _, third_party = classify_roots(modules, first_party_roots)
        third_party_roots.update(third_party)

    return third_party_roots
