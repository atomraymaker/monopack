"""Dependency graph traversal for first-party bundle selection."""

from dataclasses import dataclass
from pathlib import Path

from monopack.imports import classify_roots, extract_import_references_from_file, root_module
from monopack.module_resolver import (
    module_name_from_path,
    parent_init_files,
    resolve_module_to_file,
)


@dataclass(frozen=True)
class FirstPartyAnalysisCache:
    """Precomputed module/file and import relationships for first-party code."""

    module_to_file: dict[str, Path]
    imports_by_file: dict[Path, set[str]]


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
    analysis_cache: FirstPartyAnalysisCache | None = None,
) -> tuple[set[Path], set[str]]:
    """Walk imports from the entrypoint and collect files plus third-party roots."""

    if root_module(entrypoint_module) not in first_party_roots:
        raise ValueError(
            f"Entrypoint module {entrypoint_module!r} is not first-party."
        )

    cache = analysis_cache or build_first_party_analysis_cache(
        project_root=project_root,
        first_party_roots=first_party_roots,
    )

    selected_files: set[Path] = set()
    third_party_roots: set[str] = set()

    to_visit: list[Path] = [entrypoint_file]
    for module in sorted(extra_modules or set()):
        if root_module(module) not in first_party_roots:
            continue

        resolved = resolve_module_to_file_with_cache(module, project_root, cache)
        if resolved is None:
            continue

        to_visit.append(resolved)

    while to_visit:
        current_file = to_visit.pop()
        if current_file in selected_files:
            continue

        selected_files.add(current_file)

        imported_modules = imported_modules_from_file(current_file, project_root, cache)

        _, _, third_party = classify_roots(imported_modules, first_party_roots)
        third_party_roots.update(third_party)

        for module in sorted(imported_modules):
            if root_module(module) not in first_party_roots:
                continue

            resolved = resolve_module_to_file_with_cache(module, project_root, cache)
            if resolved is None or resolved in selected_files:
                continue
            to_visit.append(resolved)

    files_to_copy = set(selected_files)
    for module_path in selected_files:
        files_to_copy.update(parent_init_files(module_path, project_root))

    return files_to_copy, third_party_roots


def build_first_party_analysis_cache(
    project_root: Path,
    first_party_roots: set[str],
) -> FirstPartyAnalysisCache:
    """Precompute module resolution and imports for first-party files."""

    all_files: list[Path] = []
    for root in sorted(first_party_roots):
        root_dir = project_root / root
        if not root_dir.is_dir():
            continue
        all_files.extend(sorted(root_dir.rglob("*.py"), key=str))

    module_to_file: dict[str, Path] = {}
    imports_by_file: dict[Path, set[str]] = {}

    for path in all_files:
        module = module_name_from_path(path, project_root)
        existing = module_to_file.get(module)
        if existing is None or path.name != "__init__.py":
            module_to_file[module] = path

        imports_by_file[path] = imported_modules_for_path(path, project_root)

    return FirstPartyAnalysisCache(
        module_to_file=module_to_file,
        imports_by_file=imports_by_file,
    )


def resolve_module_to_file_with_cache(
    module: str,
    project_root: Path,
    cache: FirstPartyAnalysisCache,
) -> Path | None:
    """Resolve module path using cache first, then filesystem fallback."""

    resolved = cache.module_to_file.get(module)
    if resolved is not None:
        return resolved
    return resolve_module_to_file(module, project_root)


def imported_modules_from_file(
    current_file: Path,
    project_root: Path,
    cache: FirstPartyAnalysisCache,
) -> set[str]:
    """Get absolute imported module candidates for a source file."""

    cached = cache.imports_by_file.get(current_file)
    if cached is not None:
        return set(cached)
    return imported_modules_for_path(current_file, project_root)


def imported_modules_for_path(current_file: Path, project_root: Path) -> set[str]:
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

    return imported_modules
