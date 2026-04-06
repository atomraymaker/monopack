"""Core build pipeline for packaging and verifying pack bundles."""

import json
import base64
from dataclasses import dataclass
import hashlib
import os
import re
import shutil
import subprocess
import sys
import threading
from importlib.metadata import packages_distributions
from pathlib import Path
import zipfile

from monopack.discovery import resolve_pack_entrypoint
from monopack.graph import (
    FirstPartyAnalysisCache,
    build_first_party_analysis_cache,
    collect_reachable_first_party_files,
)
from monopack.imports import classify_roots, extract_imports_from_file, root_module
from monopack.inline_config import (
    InlineConfig,
    parse_inline_config,
    rewrite_inline_config,
)
from monopack.module_resolver import resolve_module_to_file
from monopack.package_manager import resolve_package_manager
from monopack.requirements import (
    filter_requirements_for_distributions,
    parse_pinned_requirements,
)
from monopack.test_mode import (
    collect_third_party_roots_from_tests,
    copy_relevant_tests,
    module_names_from_files,
)
from monopack.verifier import (
    run_unittest_discovery,
    run_verifier_script,
    write_verifier_script,
)

SUPPORTED_SHA_OUTPUTS = frozenset({"hex", "b64"})
DEFAULT_SHA_OUTPUTS = frozenset({"hex"})
DEPENDENCY_CACHE_DIRNAME = ".deps"
DEPENDENCY_LOCK_FILENAME = "requirements.lock.txt"
_MISSING_MODULE_RE = re.compile(
    r"ModuleNotFoundError:\s+No module named ['\"](?P<module>[^'\"]+)['\"]"
)
_DEPENDENCY_SYNC_CACHE: set[tuple[str, str, str, str]] = set()
_DEPENDENCY_SYNC_LOCK = threading.Lock()
_FIRST_PARTY_ANALYSIS_CACHE: dict[
    tuple[str, tuple[tuple[str, int, int], ...]],
    FirstPartyAnalysisCache,
] = {}
_FIRST_PARTY_ANALYSIS_CACHE_LOCK = threading.Lock()
_PACKAGE_MANAGER_EXPORT_COMMANDS: dict[str, list[list[str]]] = {
    "uv": [
        ["uv", "export", "--format", "requirements.txt", "--no-hashes"],
        ["uv", "export", "--format", "requirements-txt", "--no-hashes"],
    ],
    "poetry": [
        ["poetry", "export", "--format", "requirements.txt", "--without-hashes"],
        ["poetry", "export", "-f", "requirements.txt", "--without-hashes"],
    ],
    "pipenv": [
        ["pipenv", "requirements"],
        ["pipenv", "lock", "-r"],
    ],
}


@dataclass(frozen=True)
class SharedBuildState:
    """Reusable shared build artifacts for multi-pack runs."""

    lock_requirements_path: Path
    wheelhouse: Path
    package_map: dict[str, list[str]]
    analysis_cache: FirstPartyAnalysisCache


class VerificationFailedError(RuntimeError):
    """Internal marker error for verifier failures eligible for auto-fix."""

    pass


def build_pack(
    pack_name: str,
    packs_dir: Path,
    build_dir: Path,
    project_root: Path,
    verify: bool = True,
    mode: str = "deploy",
    auto_fix: bool = False,
    with_tests: bool = False,
    debug: bool = False,
    max_retries: int = 3,
    sha_outputs: set[str] | None = None,
    package_manager: str = "auto",
    existing_install_python: str | None = None,
    shared_state: SharedBuildState | None = None,
) -> Path:
    """Build one pack and optionally write deploy artifacts.

    Returns the build target directory path (`<build_dir>/<pack_name>`).
    Deploy mode writes `<build_dir>/<pack_name>.zip` plus package digest helper files.
    Test mode does not write deploy artifacts.
    """

    retries = 0
    normalized_sha_outputs = normalize_sha_outputs(sha_outputs)
    while True:
        try:
            return _build_pack_once(
                pack_name=pack_name,
                packs_dir=packs_dir,
                build_dir=build_dir,
                project_root=project_root,
                verify=verify,
                mode=mode,
                with_tests=with_tests,
                debug=debug,
                sha_outputs=normalized_sha_outputs,
                package_manager=package_manager,
                existing_install_python=existing_install_python,
                shared_state=shared_state,
            )
        except VerificationFailedError as exc:
            if not auto_fix or retries >= max_retries:
                raise RuntimeError(str(exc)) from exc

            missing_module = parse_missing_module_from_traceback(str(exc))
            if missing_module is None:
                raise RuntimeError(str(exc)) from exc

            entrypoint = resolve_pack_entrypoint(packs_dir, pack_name)
            config = parse_inline_config(entrypoint.read_text(encoding="utf-8"))
            target_kind, target_value = choose_auto_fix_target(
                missing_module=missing_module,
                project_root=project_root,
            )
            updated_config = persist_inline_config_fix(
                entrypoint=entrypoint,
                config=config,
                target_kind=target_kind,
                target_value=target_value,
            )
            if updated_config == config:
                raise RuntimeError(str(exc)) from exc

            retries += 1


def _build_pack_once(
    pack_name: str,
    packs_dir: Path,
    build_dir: Path,
    project_root: Path,
    verify: bool,
    mode: str,
    with_tests: bool,
    debug: bool,
    sha_outputs: set[str],
    package_manager: str,
    existing_install_python: str | None,
    shared_state: SharedBuildState | None,
) -> Path:
    """Execute a single build attempt without auto-fix retry handling."""

    if mode not in {"deploy", "test"}:
        raise ValueError("mode must be either 'deploy' or 'test'")

    entrypoint = resolve_pack_entrypoint(packs_dir, pack_name)
    inline_config = parse_inline_config(entrypoint.read_text(encoding="utf-8"))
    build_target = build_dir / pack_name
    effective_shared_state = shared_state or prewarm_shared_build_state(
        project_root=project_root,
        build_dir=build_dir,
        package_manager=package_manager,
        existing_install_python=existing_install_python,
        debug=debug,
    )
    lock_requirements_path = effective_shared_state.lock_requirements_path
    wheelhouse = effective_shared_state.wheelhouse
    package_map = effective_shared_state.package_map
    analysis_cache = effective_shared_state.analysis_cache

    if build_target.exists():
        shutil.rmtree(build_target)
    build_target.mkdir(parents=True)

    files_to_copy, third_party_roots = collect_reachable_first_party_files(
        entrypoint_module=f"packs.{pack_name}",
        entrypoint_file=entrypoint,
        project_root=project_root,
        extra_modules=inline_config.extra_modules,
        analysis_cache=analysis_cache,
    )

    for source_file in sorted(
        files_to_copy,
        key=lambda path: path.relative_to(project_root).as_posix(),
    ):
        relative = source_file.relative_to(project_root)
        destination = build_target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, destination)

    selected_modules = module_names_from_files(
        files_to_copy,
        project_root,
    )

    run_tests = mode == "test" or with_tests
    keep_tests_in_output = mode == "test"

    copied_tests_dir: Path | None = None
    if run_tests:
        copied_tests_dir = copy_relevant_tests(
            project_root,
            build_target,
            selected_modules,
        )
        if copied_tests_dir is None:
            raise RuntimeError(
                "No relevant tests were copied for pack "
                f"'{pack_name}'. Add tests that import the pack's "
                "runtime modules."
            )
        test_third_party_roots = collect_third_party_roots_from_tests(
            copied_tests_dir,
            project_root,
        )
        third_party_roots.update(test_third_party_roots)

    parsed_requirements = parse_pinned_requirements(lock_requirements_path)
    requirements_path = project_root / "requirements.txt"
    resolved_distributions = resolve_third_party_distributions(
        third_party_roots=third_party_roots,
        parsed_requirements=parsed_requirements,
        package_map=package_map,
        project_root=project_root,
        requirements_path=requirements_path,
    )
    resolved_distributions.update(inline_config.extra_distributions)
    per_pack_requirements = filter_requirements_for_distributions(
        parsed_requirements,
        resolved_distributions,
    )

    requirements_path = build_target / "requirements.txt"
    if per_pack_requirements:
        requirements_path.write_text(
            "\n".join(per_pack_requirements) + "\n",
            encoding="utf-8",
        )
        _pip_install_target(
            build_target,
            requirements_path,
            find_links=wheelhouse,
            no_index=True,
        )

    verifier_path = build_target / "_monopack_verify.py"
    write_verifier_script(verifier_path, pack_name, selected_modules)

    if verify:
        try:
            run_verifier_script(verifier_path, cwd=build_target)
        except RuntimeError as exc:
            raise VerificationFailedError(str(exc)) from exc

    if verify and run_tests and copied_tests_dir is not None:
        try:
            run_unittest_discovery(copied_tests_dir, cwd=build_target)
        except RuntimeError as exc:
            raise VerificationFailedError(str(exc)) from exc
        if not keep_tests_in_output:
            shutil.rmtree(copied_tests_dir)

    if debug:
        report = build_debug_report(
            pack_name=pack_name,
            mode=mode,
            verify=verify,
            run_tests=run_tests,
            build_target=build_target,
            selected_modules=selected_modules,
            files_to_copy=files_to_copy,
            copied_tests_dir=copied_tests_dir,
            parsed_requirements=parsed_requirements,
            package_map=package_map,
            per_pack_requirements=per_pack_requirements,
            project_root=project_root,
        )
        print(report, file=sys.stderr)

    if mode == "deploy":
        write_package_sha_files(
            build_target=build_target,
            output_prefix=build_dir / pack_name,
            sha_outputs=sha_outputs,
        )
        create_build_artifact_zip(
            build_target=build_target,
            artifact_path=build_dir / f"{pack_name}.zip",
        )

    return build_target


def create_build_artifact_zip(build_target: Path, artifact_path: Path) -> Path:
    """Create a zip artifact from a build target."""

    files = sorted(
        (path for path in build_target.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(build_target).as_posix(),
    )

    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        artifact_path, mode="w", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        for file_path in files:
            relative_path = file_path.relative_to(build_target).as_posix()
            archive.write(file_path, arcname=relative_path)

    return artifact_path


def normalize_sha_outputs(sha_outputs: set[str] | None) -> set[str]:
    if sha_outputs is None:
        return set(DEFAULT_SHA_OUTPUTS)

    normalized = {value.strip().lower() for value in sha_outputs if value.strip()}
    if not normalized:
        return set(DEFAULT_SHA_OUTPUTS)

    invalid = sorted(normalized - SUPPORTED_SHA_OUTPUTS)
    if invalid:
        raise ValueError(
            f"Unsupported sha output values: {', '.join(invalid)}. "
            "Supported values: b64, hex."
        )

    return normalized


def package_content_digest(build_target: Path) -> bytes:
    """Compute deterministic digest bytes for package content."""

    digest = hashlib.sha256()
    file_paths = sorted(
        path
        for path in build_target.rglob("*")
        if path.is_file() and _included_in_package_hash(path, build_target)
    )

    for file_path in file_paths:
        relative_path = file_path.relative_to(build_target).as_posix().encode("utf-8")
        file_hash = hashlib.sha256(file_path.read_bytes()).hexdigest().encode("ascii")
        digest.update(relative_path)
        digest.update(b"\0")
        digest.update(file_hash)
        digest.update(b"\n")

    return digest.digest()


def write_package_sha_files(
    build_target: Path, output_prefix: Path, sha_outputs: set[str]
) -> list[Path]:
    """Write selected package digest output files for deploy workflows."""

    normalized_outputs = normalize_sha_outputs(sha_outputs)
    digest_bytes = package_content_digest(build_target)
    written: list[Path] = []

    if "hex" in normalized_outputs:
        hex_path = output_prefix.parent / f"{output_prefix.name}.package.sha256"
        hex_path.parent.mkdir(parents=True, exist_ok=True)
        hex_path.write_text(f"{digest_bytes.hex()}\n", encoding="utf-8")
        written.append(hex_path)

    if "b64" in normalized_outputs:
        b64_value = base64.b64encode(digest_bytes).decode("ascii")
        b64_path = output_prefix.parent / f"{output_prefix.name}.package.sha256.b64"
        b64_path.parent.mkdir(parents=True, exist_ok=True)
        b64_path.write_text(f"{b64_value}\n", encoding="utf-8")
        written.append(b64_path)

    return written


def write_package_sha_file(build_target: Path, output_path: Path) -> Path:
    """Write a deterministic package digest for deploy change detection."""
    digest_bytes = package_content_digest(build_target)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(f"{digest_bytes.hex()}\n", encoding="utf-8")
    return output_path


def _included_in_package_hash(path: Path, build_target: Path) -> bool:
    relative = path.relative_to(build_target)
    return "__pycache__" not in relative.parts and path.suffix != ".pyc"


def parse_missing_module_from_traceback(traceback_text: str) -> str | None:
    """Extract missing module name from verifier traceback text."""

    match = _MISSING_MODULE_RE.search(traceback_text)
    if match is None:
        return None
    return match.group("module")


def choose_auto_fix_target(
    missing_module: str,
    project_root: Path,
    packages_to_distributions: dict[str, list[str]] | None = None,
) -> tuple[str, str]:
    """Choose whether auto-fix should add a module or a distribution override."""

    missing_root = root_module(missing_module)
    if resolve_module_to_file(missing_module, project_root):
        return "module", missing_module

    package_map = packages_to_distributions
    if package_map is None:
        package_map = packages_distributions()

    distributions = sorted(package_map.get(missing_root, []), key=str.lower)
    if distributions:
        return "distribution", distributions[0]
    return "distribution", missing_root


def persist_inline_config_fix(
    entrypoint: Path,
    config: InlineConfig,
    target_kind: str,
    target_value: str,
) -> InlineConfig:
    """Apply and persist an inline-config auto-fix to a pack entrypoint."""

    if target_kind == "module":
        updated = InlineConfig(
            extra_modules=set(config.extra_modules) | {target_value},
            extra_distributions=set(config.extra_distributions),
        )
    elif target_kind == "distribution":
        updated = InlineConfig(
            extra_modules=set(config.extra_modules),
            extra_distributions=set(config.extra_distributions) | {target_value},
        )
    else:
        raise ValueError(f"Unsupported auto-fix target kind: {target_kind}")

    if updated == config:
        return config

    source = entrypoint.read_text(encoding="utf-8")
    rewritten = rewrite_inline_config(source, updated)
    entrypoint.write_text(rewritten, encoding="utf-8")
    return updated


def _pip_install_target(
    build_target: Path,
    requirements_path: Path,
    find_links: Path | None = None,
    no_index: bool = False,
) -> None:
    """Install selected dependencies into the build target with pip."""

    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--target",
        str(build_target),
        "-r",
        str(requirements_path),
    ]
    if no_index:
        command.append("--no-index")
    if find_links is not None:
        command.extend(["--find-links", str(find_links)])
    completed = _run_pip_install(
        command, build_target, requirements_path, no_index, find_links
    )
    if completed.returncode == 0:
        return

    if no_index or find_links is not None:
        retry_command = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--target",
            str(build_target),
            "-r",
            str(requirements_path),
        ]
        retry = _run_pip_install(
            retry_command,
            build_target,
            requirements_path,
            no_index=False,
            find_links=None,
        )
        if retry.returncode == 0:
            return

        raise RuntimeError(
            "Dependency installation failed after local-wheelhouse and online fallback attempts. "
            f"local stdout:\n{completed.stdout}\n"
            f"local stderr:\n{completed.stderr}\n"
            f"online stdout:\n{retry.stdout}\n"
            f"online stderr:\n{retry.stderr}"
        )

    raise RuntimeError(
        "Dependency installation failed. "
        f"stdout:\n{completed.stdout}\n"
        f"stderr:\n{completed.stderr}"
    )


def _run_pip_install(
    command: list[str],
    build_target: Path,
    requirements_path: Path,
    no_index: bool,
    find_links: Path | None,
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Dependency installation failed: pip is not available. "
            "Install pip or run in an environment where pip is present."
        ) from exc

    if completed.returncode != 0 and "No module named pip" in completed.stderr:
        try:
            return subprocess.run(
                [
                    "pip",
                    "install",
                    "--target",
                    str(build_target),
                    "-r",
                    str(requirements_path),
                ]
                + (["--no-index"] if no_index else [])
                + (["--find-links", str(find_links)] if find_links is not None else []),
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "Dependency installation failed: neither 'python -m pip' nor 'pip' "
                "is available. Install pip before running builds with dependencies."
            ) from exc

    return completed


def _normalize_distribution_name(name: str) -> str:
    return name.lower().replace("_", "-")


def resolve_third_party_distributions(
    third_party_roots: set[str],
    parsed_requirements: dict[str, str],
    package_map: dict[str, list[str]],
    project_root: Path | None = None,
    requirements_path: Path | None = None,
) -> set[str]:
    """Resolve import roots to distribution names present in pinned lock requirements."""

    resolved: set[str] = set()
    unresolved: list[str] = []

    for root in sorted(third_party_roots):
        normalized_root = _normalize_distribution_name(root)
        if normalized_root in parsed_requirements:
            resolved.add(root)
            continue

        candidates = package_map.get(root, [])
        if not candidates:
            candidates = package_map.get(root.lower(), [])

        matching_candidates = [
            candidate
            for candidate in candidates
            if _normalize_distribution_name(candidate) in parsed_requirements
        ]
        if matching_candidates:
            resolved.add(sorted(matching_candidates, key=str.lower)[0])
            continue

        unresolved.append(root)

    if unresolved:
        unresolved_display = ", ".join(unresolved)
        project_root_display = (
            str(project_root) if project_root is not None else "<project_root>"
        )
        requirements_display = (
            str(requirements_path)
            if requirements_path is not None
            else "<project_root>/requirements.txt"
        )
        raise KeyError(
            "Could not resolve imports to pinned third-party distributions: "
            f"{unresolved_display}. Checked local modules under {project_root_display} "
            f"and pinned lock requirements in {requirements_display}. "
            "If these are third-party imports, ensure they resolve to installed distributions "
            "during dependency sync. "
            "If these are local modules, ensure they resolve under the project root."
        )

    return resolved


def _local_root_candidate_path(root: str, project_root: Path) -> Path | None:
    module_file = project_root / f"{root}.py"
    if module_file.exists():
        return module_file

    package_dir = project_root / root
    if package_dir.is_dir():
        package_init = package_dir / "__init__.py"
        if package_init.exists():
            return package_init
        return package_dir

    return None


def prepare_source_requirements(
    project_root: Path,
    deps_root: Path,
    package_manager: str,
) -> Path:
    """Prepare a requirements source file for dependency cache sync."""

    if package_manager == "pip":
        requirements_path = project_root / "requirements.txt"
        if not requirements_path.is_file():
            raise FileNotFoundError(
                "Missing required requirements file at "
                f"{requirements_path}. Add a project-level requirements.txt."
            )
        return requirements_path

    export_commands = _PACKAGE_MANAGER_EXPORT_COMMANDS.get(package_manager)
    if not export_commands:
        raise ValueError(
            f"Unsupported package manager '{package_manager}' for dependency export."
        )

    deps_root.mkdir(parents=True, exist_ok=True)
    output_path = deps_root / f"{package_manager}.requirements.txt"

    failures: list[str] = []
    for command in export_commands:
        completed = subprocess.run(
            command,
            cwd=project_root,
            capture_output=True,
            text=True,
        )
        if completed.returncode == 0:
            output_path.write_text(completed.stdout, encoding="utf-8")
            return output_path

        failures.append(
            f"$ {' '.join(command)}\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )

    details = "\n\n".join(failures)
    raise RuntimeError(
        "Failed to export requirements from package manager "
        f"'{package_manager}'. Tried the following commands:\n\n{details}"
    )


def _resolve_python_candidate_path(candidate: str, project_root: Path) -> Path:
    path = Path(candidate).expanduser()
    if not path.is_absolute():
        path = (project_root / path).resolve()
    return path


def _python_from_virtualenv_path(env_path: str, project_root: Path) -> Path | None:
    resolved = _resolve_python_candidate_path(env_path, project_root)
    python_path = resolved / "bin" / "python"
    if python_path.is_file():
        return python_path
    return None


def _poetry_env_python(project_root: Path) -> Path | None:
    completed = subprocess.run(
        ["poetry", "env", "info", "-p"],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return None

    env_path = completed.stdout.strip()
    if not env_path:
        return None

    return _python_from_virtualenv_path(env_path, project_root)


def _pipenv_env_python(project_root: Path) -> Path | None:
    completed = subprocess.run(
        ["pipenv", "--venv"],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return None

    env_path = completed.stdout.strip()
    if not env_path:
        return None

    return _python_from_virtualenv_path(env_path, project_root)


def _discover_existing_install_python(
    project_root: Path,
    package_manager: str,
    override_python: str | None,
) -> tuple[Path | None, str]:
    if override_python:
        override_path = _resolve_python_candidate_path(override_python, project_root)
        if override_path.is_file():
            return override_path, "override"
        return None, f"override not found: {override_path}"

    candidates: list[tuple[Path, str]] = []
    seen: set[Path] = set()

    def add_candidate(path: Path, source: str) -> None:
        resolved_path = path.resolve()
        if resolved_path in seen:
            return
        seen.add(resolved_path)
        candidates.append((resolved_path, source))

    venv_env = os.environ.get("VIRTUAL_ENV")
    if venv_env:
        python_path = Path(venv_env) / "bin" / "python"
        if python_path.is_file():
            add_candidate(python_path, "VIRTUAL_ENV")

    for relative in (".venv/bin/python", "venv/bin/python", "env/bin/python"):
        candidate = project_root / relative
        if candidate.is_file():
            add_candidate(candidate, f"project:{relative}")

    if package_manager == "poetry":
        poetry_python = _poetry_env_python(project_root)
        if poetry_python is not None:
            add_candidate(poetry_python, "poetry env")
    elif package_manager == "pipenv":
        pipenv_python = _pipenv_env_python(project_root)
        if pipenv_python is not None:
            add_candidate(pipenv_python, "pipenv --venv")

    if not candidates:
        return None, "no install candidate found"

    selected, source = candidates[0]
    return selected, source


def _pip_cache_dir_for_python(python_executable: Path) -> Path | None:
    completed = subprocess.run(
        [str(python_executable), "-m", "pip", "cache", "dir"],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return None

    cache_dir = completed.stdout.strip()
    if not cache_dir:
        return None

    return Path(cache_dir)


def sync_dependency_cache(
    project_root: Path,
    build_dir: Path,
    package_manager: str,
    existing_install_python: str | None = None,
    debug: bool = False,
) -> tuple[Path, Path, dict[str, list[str]]]:
    """Install top-level deps once per build invocation and return lock + wheelhouse."""

    deps_root = build_dir / DEPENDENCY_CACHE_DIRNAME
    resolved_package_manager = resolve_package_manager(project_root, package_manager)
    source_requirements = prepare_source_requirements(
        project_root=project_root,
        deps_root=deps_root,
        package_manager=resolved_package_manager,
    )
    requirements_text = source_requirements.read_text(encoding="utf-8")
    cache_key: tuple[str, str, str, str] = (
        str(project_root.resolve()),
        str(build_dir.resolve()),
        resolved_package_manager,
        requirements_text,
    )

    deps_venv = deps_root / "venv"
    lock_path = deps_root / DEPENDENCY_LOCK_FILENAME
    wheelhouse = deps_root / "wheelhouse"
    discovered_python, discovered_source = _discover_existing_install_python(
        project_root=project_root,
        package_manager=resolved_package_manager,
        override_python=existing_install_python,
    )
    report_fallback = debug or existing_install_python is not None
    cache_dir: Path | None = None
    if discovered_python is not None:
        cache_dir = _pip_cache_dir_for_python(discovered_python)
        if cache_dir is not None and debug:
            print(
                "[debug] Reusing dependency install cache from "
                f"{discovered_python} ({discovered_source}), pip_cache={cache_dir}",
                file=sys.stderr,
            )
        elif cache_dir is None and report_fallback:
            print(
                "[build] Existing install was found but no reusable pip cache was available; "
                "falling back to normal dependency cache sync.",
                file=sys.stderr,
            )
    else:
        if report_fallback:
            print(
                "[build] No existing install cache found; using normal dependency cache sync.",
                file=sys.stderr,
            )
        if debug:
            print(
                f"[debug] Existing install detection details: {discovered_source}",
                file=sys.stderr,
            )

    with _DEPENDENCY_SYNC_LOCK:
        if (
            cache_key in _DEPENDENCY_SYNC_CACHE
            and lock_path.exists()
            and wheelhouse.exists()
        ):
            package_map = _packages_distributions_from_python(
                deps_venv / "bin" / "python"
            )
            return lock_path, wheelhouse, package_map

        deps_root.mkdir(parents=True, exist_ok=True)
        wheelhouse.mkdir(parents=True, exist_ok=True)

        if not deps_venv.exists():
            _run_checked(
                [sys.executable, "-m", "venv", str(deps_venv)],
                "Failed to create dependency venv",
            )

        deps_python = deps_venv / "bin" / "python"

        _run_checked(
            [
                str(deps_python),
                "-m",
                "pip",
                "install",
                "-r",
                str(source_requirements),
            ]
            + (["--cache-dir", str(cache_dir)] if cache_dir is not None else []),
            "Failed to install top-level requirements into dependency cache",
        )

        freeze_output = _run_checked(
            [str(deps_python), "-m", "pip", "freeze", "--exclude-editable"],
            "Failed to freeze dependency cache",
        )
        lock_path.write_text(freeze_output.stdout, encoding="utf-8")

        _run_checked(
            [
                str(deps_python),
                "-m",
                "pip",
                "download",
                "--dest",
                str(wheelhouse),
                "-r",
                str(lock_path),
            ]
            + (["--cache-dir", str(cache_dir)] if cache_dir is not None else []),
            "Failed to prepare local dependency wheelhouse",
        )

        package_map = _packages_distributions_from_python(deps_python)
        _DEPENDENCY_SYNC_CACHE.add(cache_key)
        return lock_path, wheelhouse, package_map


def prewarm_shared_build_state(
    project_root: Path,
    build_dir: Path,
    package_manager: str = "auto",
    existing_install_python: str | None = None,
    debug: bool = False,
) -> SharedBuildState:
    """Compute reusable dependency and import analysis state once."""

    lock_requirements_path, wheelhouse, package_map = sync_dependency_cache(
        project_root=project_root,
        build_dir=build_dir,
        package_manager=package_manager,
        existing_install_python=existing_install_python,
        debug=debug,
    )
    analysis_cache = get_first_party_analysis_cache(project_root)
    return SharedBuildState(
        lock_requirements_path=lock_requirements_path,
        wheelhouse=wheelhouse,
        package_map=package_map,
        analysis_cache=analysis_cache,
    )


def get_first_party_analysis_cache(
    project_root: Path,
) -> FirstPartyAnalysisCache:
    """Return a reusable first-party import analysis cache for this process."""

    key = (
        str(project_root.resolve()),
        _runtime_python_file_signature(project_root),
    )
    with _FIRST_PARTY_ANALYSIS_CACHE_LOCK:
        cached = _FIRST_PARTY_ANALYSIS_CACHE.get(key)
        if cached is not None:
            return cached

        cache = build_first_party_analysis_cache(
            project_root=project_root,
        )
        _FIRST_PARTY_ANALYSIS_CACHE[key] = cache
        return cache


def _runtime_python_file_signature(
    project_root: Path,
) -> tuple[tuple[str, int, int], ...]:
    """Return a content-shape signature for runtime Python files."""

    excluded_roots = {"tests", "build", "dist", "venv", ".venv"}
    entries: list[tuple[str, int, int]] = []

    for path in sorted(project_root.rglob("*.py"), key=str):
        relative = path.relative_to(project_root)
        if not relative.parts or relative.parts[0] in excluded_roots:
            continue
        if any(
            part.startswith(".") or part == "__pycache__" for part in relative.parts
        ):
            continue
        try:
            stat = path.stat()
        except FileNotFoundError:
            continue
        entries.append((relative.as_posix(), stat.st_mtime_ns, stat.st_size))

    return tuple(entries)


def _packages_distributions_from_python(
    python_executable: Path,
) -> dict[str, list[str]]:
    output = _run_checked(
        [
            str(python_executable),
            "-c",
            (
                "import json; "
                "from importlib.metadata import packages_distributions; "
                "print(json.dumps(packages_distributions()))"
            ),
        ],
        "Failed to read package-to-distribution mapping from dependency cache",
    )
    return json.loads(output.stdout)


def _run_checked(
    command: list[str],
    failure_message: str,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(command, capture_output=True, text=True, cwd=cwd)
    if completed.returncode == 0:
        return completed

    raise RuntimeError(
        f"{failure_message}. stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )


def build_debug_report(
    *,
    pack_name: str,
    mode: str,
    verify: bool,
    run_tests: bool,
    build_target: Path,
    selected_modules: set[str],
    files_to_copy: set[Path],
    copied_tests_dir: Path | None,
    parsed_requirements: dict[str, str],
    package_map: dict[str, list[str]],
    per_pack_requirements: list[str],
    project_root: Path,
) -> str:
    import_roots = collect_import_roots(files_to_copy)
    if copied_tests_dir is not None and copied_tests_dir.exists():
        import_roots.update(collect_import_roots(set(copied_tests_dir.rglob("*.py"))))

    first_party_imports, stdlib_imports, third_party_imports = classify_roots(
        {root for root in import_roots},
        project_root,
    )

    third_party_resolution_lines: list[str] = []
    for root in sorted(third_party_imports):
        normalized_root = _normalize_distribution_name(root)
        if normalized_root in parsed_requirements:
            third_party_resolution_lines.append(
                f"- {root}: requirements ({parsed_requirements[normalized_root]})"
            )
            continue

        local_candidate = _local_root_candidate_path(root, project_root)
        if local_candidate is not None:
            location = local_candidate.relative_to(project_root).as_posix()
            third_party_resolution_lines.append(f"- {root}: local-module ({location})")
            continue

        candidates = package_map.get(root, []) or package_map.get(root.lower(), [])
        matching = [
            candidate
            for candidate in candidates
            if _normalize_distribution_name(candidate) in parsed_requirements
        ]
        if matching:
            chosen = sorted(matching, key=str.lower)[0]
            pinned = parsed_requirements[_normalize_distribution_name(chosen)]
            third_party_resolution_lines.append(
                f"- {root}: package-map ({chosen} -> {pinned})"
            )
            continue

        third_party_resolution_lines.append("- {root}: unresolved".format(root=root))

    tests_count = 0
    if copied_tests_dir is not None and copied_tests_dir.exists():
        tests_count = len([path for path in copied_tests_dir.rglob("test*.py")])

    lines = [
        f"[debug] Build report for '{pack_name}'",
        f"  mode={mode} verify={verify} run_tests={run_tests}",
        f"  build_target={build_target}",
        f"  copied_first_party_files={len(files_to_copy)} selected_modules={len(selected_modules)}",
        "  import_roots="
        f"first_party:{len(first_party_imports)} stdlib:{len(stdlib_imports)} third_party:{len(third_party_imports)}",
        f"  copied_tests={tests_count}",
        f"  selected_requirements={len(per_pack_requirements)}",
    ]

    if per_pack_requirements:
        lines.append("  requirements:")
        lines.extend(f"    - {requirement}" for requirement in per_pack_requirements)

    if third_party_resolution_lines:
        lines.append("  third_party_resolution:")
        lines.extend(f"    {line}" for line in third_party_resolution_lines)

    return "\n".join(lines)


def collect_import_roots(paths: set[Path]) -> set[str]:
    roots: set[str] = set()
    for path in sorted(paths, key=str):
        if not path.is_file() or path.suffix != ".py":
            continue
        for module in extract_imports_from_file(path):
            roots.add(root_module(module))
    return roots
