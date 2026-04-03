"""Dependency graph traversal for first-party bundle selection."""

from pathlib import Path

from monopack.imports import classify_roots, extract_import_references_from_file, root_module
from monopack.module_resolver import (
    module_name_from_path,
    parent_init_files,
    resolve_module_to_file,
)


def resolve_relative_import_base_module(
    current_module: str,
    level: int,
    module: str | None,
    is_package: bool = False,
) -> str | None:
    """Resolve the absolute module base for a relative import reference."""

    if level <= 0:
        return module

    module_parts = current_module.split(".")
    if is_package:
        current_package_parts = list(module_parts)
    elif len(module_parts) == 1:
        current_package_parts = []
    else:
        current_package_parts = module_parts[:-1]

    parent_hops = level - 1
    if parent_hops > len(current_package_parts):
        return None

    base_parts = current_package_parts[: len(current_package_parts) - parent_hops]
    if module:
        base_parts.extend(module.split("."))
    if not base_parts:
        return None
    return ".".join(base_parts)


def imported_module_candidates(
    current_module: str,
    level: int,
    module: str | None,
    imported_names: tuple[str, ...],
    is_package: bool = False,
) -> list[str]:
    """Return candidate absolute modules implied by an import statement."""

    base = resolve_relative_import_base_module(
        current_module,
        level,
        module,
        is_package=is_package,
    )
    if base is None:
        return []

    candidates: list[str] = [base]
    for imported_name in imported_names:
        if imported_name == "*":
            continue
        candidates.append(f"{base}.{imported_name}")

    unique_candidates: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        unique_candidates.append(candidate)

    return unique_candidates


def collect_reachable_first_party_files(
    entrypoint_module: str,
    entrypoint_file: Path,
    project_root: Path,
    first_party_roots: set[str],
    extra_modules: set[str] | None = None,
) -> tuple[set[Path], set[str]]:
    """Walk imports from the entrypoint and collect files plus third-party roots."""

    if root_module(entrypoint_module) not in first_party_roots:
        raise ValueError(
            f"Entrypoint module {entrypoint_module!r} is not first-party."
        )

    selected_files: set[Path] = set()
    third_party_roots: set[str] = set()

    to_visit: list[Path] = [entrypoint_file]
    for module in sorted(extra_modules or set()):
        if root_module(module) not in first_party_roots:
            continue

        resolved = resolve_module_to_file(module, project_root)
        if resolved is None:
            continue

        to_visit.append(resolved)

    while to_visit:
        current_file = to_visit.pop()
        if current_file in selected_files:
            continue

        selected_files.add(current_file)

        imported_modules: set[str] = set()
        current_module = module_name_from_path(current_file, project_root)
        is_package = current_file.name == "__init__.py"
        for ref in extract_import_references_from_file(current_file):
            if ref.module is None and ref.level == 0:
                continue

            for candidate in imported_module_candidates(
                current_module=current_module,
                level=ref.level,
                module=ref.module,
                imported_names=ref.imported_names,
                is_package=is_package,
            ):
                imported_modules.add(candidate)

        _, _, third_party = classify_roots(imported_modules, first_party_roots)
        third_party_roots.update(third_party)

        for module in sorted(imported_modules):
            if root_module(module) not in first_party_roots:
                continue

            resolved = resolve_module_to_file(module, project_root)
            if resolved is None or resolved in selected_files:
                continue
            to_visit.append(resolved)

    files_to_copy = set(selected_files)
    for module_path in selected_files:
        files_to_copy.update(parent_init_files(module_path, project_root))

    return files_to_copy, third_party_roots
