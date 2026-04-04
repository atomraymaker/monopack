"""Core build pipeline for packaging and verifying function bundles."""

import json
import base64
from dataclasses import dataclass
import hashlib
import re
import shutil
import subprocess
import sys
import threading
from importlib.metadata import packages_distributions
from pathlib import Path
import zipfile

from monopack.discovery import resolve_entrypoint
from monopack.graph import (
    FirstPartyAnalysisCache,
    build_first_party_analysis_cache,
    collect_reachable_first_party_files,
)
from monopack.imports import classify_roots, extract_imports_from_file, root_module
from monopack.inline_config import InlineConfig, parse_inline_config, rewrite_inline_config
from monopack.module_resolver import resolve_module_to_file
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


FIRST_PARTY_ROOTS = {"functions", "app", "lib"}
SUPPORTED_SHA_OUTPUTS = frozenset({"hex", "b64"})
DEFAULT_SHA_OUTPUTS = frozenset({"hex"})
DEPENDENCY_CACHE_DIRNAME = ".deps"
DEPENDENCY_LOCK_FILENAME = "requirements.lock.txt"
_MISSING_MODULE_RE = re.compile(
    r"ModuleNotFoundError:\s+No module named ['\"](?P<module>[^'\"]+)['\"]"
)
_DEPENDENCY_SYNC_CACHE: set[tuple[str, str, str]] = set()
_DEPENDENCY_SYNC_LOCK = threading.Lock()
_FIRST_PARTY_ANALYSIS_CACHE: dict[
    tuple[str, tuple[str, ...]],
    FirstPartyAnalysisCache,
] = {}
_FIRST_PARTY_ANALYSIS_CACHE_LOCK = threading.Lock()


@dataclass(frozen=True)
class SharedBuildState:
    """Reusable shared build artifacts for multi-function runs."""

    lock_requirements_path: Path
    wheelhouse: Path
    package_map: dict[str, list[str]]
    analysis_cache: FirstPartyAnalysisCache


class VerificationFailedError(RuntimeError):
    """Internal marker error for verifier failures eligible for auto-fix."""

    pass


def build_function(
    function_name: str,
    functions_dir: Path,
    build_dir: Path,
    project_root: Path,
    verify: bool = True,
    mode: str = "deploy",
    auto_fix: bool = False,
    with_tests: bool = False,
    debug: bool = False,
    max_retries: int = 3,
    sha_outputs: set[str] | None = None,
    shared_state: SharedBuildState | None = None,
) -> Path:
    """Build one function and optionally write deploy artifacts.

    Returns the build target directory path (`<build_dir>/<function_name>`).
    Deploy mode writes `<build_dir>/<function_name>.zip` plus package digest helper files.
    Test mode does not write deploy artifacts.
    """

    retries = 0
    normalized_sha_outputs = normalize_sha_outputs(sha_outputs)
    while True:
        try:
            return _build_function_once(
                function_name=function_name,
                functions_dir=functions_dir,
                build_dir=build_dir,
                project_root=project_root,
                verify=verify,
                mode=mode,
                with_tests=with_tests,
                debug=debug,
                sha_outputs=normalized_sha_outputs,
                shared_state=shared_state,
            )
        except VerificationFailedError as exc:
            if not auto_fix or retries >= max_retries:
                raise RuntimeError(str(exc)) from exc

            missing_module = parse_missing_module_from_traceback(str(exc))
            if missing_module is None:
                raise RuntimeError(str(exc)) from exc

            entrypoint = resolve_entrypoint(functions_dir, function_name)
            config = parse_inline_config(entrypoint.read_text(encoding="utf-8"))
            target_kind, target_value = choose_auto_fix_target(
                missing_module=missing_module,
                project_root=project_root,
                first_party_roots=FIRST_PARTY_ROOTS,
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


def _build_function_once(
    function_name: str,
    functions_dir: Path,
    build_dir: Path,
    project_root: Path,
    verify: bool,
    mode: str,
    with_tests: bool,
    debug: bool,
    sha_outputs: set[str],
    shared_state: SharedBuildState | None,
) -> Path:
    """Execute a single build attempt without auto-fix retry handling."""

    if mode not in {"deploy", "test"}:
        raise ValueError("mode must be either 'deploy' or 'test'")

    entrypoint = resolve_entrypoint(functions_dir, function_name)
    inline_config = parse_inline_config(entrypoint.read_text(encoding="utf-8"))
    build_target = build_dir / function_name
    effective_shared_state = shared_state or prewarm_shared_build_state(
        project_root=project_root,
        build_dir=build_dir,
        first_party_roots=FIRST_PARTY_ROOTS,
    )
    lock_requirements_path = effective_shared_state.lock_requirements_path
    wheelhouse = effective_shared_state.wheelhouse
    package_map = effective_shared_state.package_map
    analysis_cache = effective_shared_state.analysis_cache

    if build_target.exists():
        shutil.rmtree(build_target)
    build_target.mkdir(parents=True)

    files_to_copy, third_party_roots = collect_reachable_first_party_files(
        entrypoint_module=f"functions.{function_name}",
        entrypoint_file=entrypoint,
        project_root=project_root,
        first_party_roots=FIRST_PARTY_ROOTS,
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
        FIRST_PARTY_ROOTS,
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
                "No relevant tests were copied for function "
                f"'{function_name}'. Add tests that import the function's "
                "runtime modules."
            )
        test_third_party_roots = collect_third_party_roots_from_tests(
            copied_tests_dir,
            FIRST_PARTY_ROOTS,
        )
        third_party_roots.update(test_third_party_roots)

    parsed_requirements = parse_pinned_requirements(lock_requirements_path)
    requirements_path = project_root / "requirements.txt"
    raise_for_local_roots_outside_first_party(
        third_party_roots=third_party_roots,
        parsed_requirements=parsed_requirements,
        project_root=project_root,
        requirements_path=requirements_path,
        first_party_roots=FIRST_PARTY_ROOTS,
    )
    resolved_distributions = resolve_third_party_distributions(
        third_party_roots=third_party_roots,
        parsed_requirements=parsed_requirements,
        package_map=package_map,
        project_root=project_root,
        requirements_path=requirements_path,
        first_party_roots=FIRST_PARTY_ROOTS,
    )
    resolved_distributions.update(inline_config.extra_distributions)
    per_function_requirements = filter_requirements_for_distributions(
        parsed_requirements,
        resolved_distributions,
    )

    requirements_path = build_target / "requirements.txt"
    if per_function_requirements:
        requirements_path.write_text(
            "\n".join(per_function_requirements) + "\n",
            encoding="utf-8",
        )
        _pip_install_target(
            build_target,
            requirements_path,
            find_links=wheelhouse,
            no_index=True,
        )

    verifier_path = build_target / "_monopack_verify.py"
    write_verifier_script(verifier_path, function_name, selected_modules)

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
            function_name=function_name,
            mode=mode,
            verify=verify,
            run_tests=run_tests,
            build_target=build_target,
            selected_modules=selected_modules,
            files_to_copy=files_to_copy,
            copied_tests_dir=copied_tests_dir,
            parsed_requirements=parsed_requirements,
            package_map=package_map,
            per_function_requirements=per_function_requirements,
            first_party_roots=FIRST_PARTY_ROOTS,
            project_root=project_root,
        )
        print(report, file=sys.stderr)

    if mode == "deploy":
        write_package_sha_files(
            build_target=build_target,
            output_prefix=build_dir / function_name,
            sha_outputs=sha_outputs,
        )
        create_build_artifact_zip(
            build_target=build_target,
            artifact_path=build_dir / f"{function_name}.zip",
        )

    return build_target


def create_build_artifact_zip(build_target: Path, artifact_path: Path) -> Path:
    """Create a zip artifact from a build target."""

    files = sorted(
        (path for path in build_target.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(build_target).as_posix(),
    )

    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(artifact_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
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
        path for path in build_target.rglob("*") if path.is_file() and _included_in_package_hash(path, build_target)
    )

    for file_path in file_paths:
        relative_path = file_path.relative_to(build_target).as_posix().encode("utf-8")
        file_hash = hashlib.sha256(file_path.read_bytes()).hexdigest().encode("ascii")
        digest.update(relative_path)
        digest.update(b"\0")
        digest.update(file_hash)
        digest.update(b"\n")

    return digest.digest()


def write_package_sha_files(build_target: Path, output_prefix: Path, sha_outputs: set[str]) -> list[Path]:
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
    posix_path = relative.as_posix()
    if posix_path in {"requirements.txt", "_monopack_verify.py"}:
        return True

    if not relative.parts:
        return False

    return relative.parts[0] in FIRST_PARTY_ROOTS | {"tests"}


def parse_missing_module_from_traceback(traceback_text: str) -> str | None:
    """Extract missing module name from verifier traceback text."""

    match = _MISSING_MODULE_RE.search(traceback_text)
    if match is None:
        return None
    return match.group("module")


def choose_auto_fix_target(
    missing_module: str,
    project_root: Path,
    first_party_roots: set[str],
    packages_to_distributions: dict[str, list[str]] | None = None,
) -> tuple[str, str]:
    """Choose whether auto-fix should add a module or a distribution override."""

    missing_root = root_module(missing_module)
    if missing_root in first_party_roots or resolve_module_to_file(missing_module, project_root):
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
    """Apply and persist an inline-config auto-fix to a function entrypoint."""

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
            completed = subprocess.run(
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

    if completed.returncode == 0:
        return

    raise RuntimeError(
        "Dependency installation failed. "
        f"stdout:\n{completed.stdout}\n"
        f"stderr:\n{completed.stderr}"
    )


def _normalize_distribution_name(name: str) -> str:
    return name.lower().replace("_", "-")


def resolve_third_party_distributions(
    third_party_roots: set[str],
    parsed_requirements: dict[str, str],
    package_map: dict[str, list[str]],
    project_root: Path | None = None,
    requirements_path: Path | None = None,
    first_party_roots: set[str] | None = None,
) -> set[str]:
    """Resolve import roots to distribution names present in pinned requirements."""

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
        roots_display = ", ".join(sorted(first_party_roots or set()))
        project_root_display = str(project_root) if project_root is not None else "<project_root>"
        requirements_display = (
            str(requirements_path)
            if requirements_path is not None
            else "<project_root>/requirements.txt"
        )
        raise KeyError(
            "Could not resolve imports to pinned third-party distributions: "
            f"{unresolved_display}. Checked local modules under {project_root_display} "
            f"and pinned requirements in {requirements_display}. "
            "If these are third-party imports, add pinned 'name==version' entries. "
            f"If these are local modules, place them under first-party roots ({roots_display})."
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


def raise_for_local_roots_outside_first_party(
    third_party_roots: set[str],
    parsed_requirements: dict[str, str],
    project_root: Path,
    requirements_path: Path,
    first_party_roots: set[str],
) -> None:
    """Fail early when imports look local but sit outside supported roots."""

    offenders: list[tuple[str, str]] = []
    for root in sorted(third_party_roots):
        normalized_root = _normalize_distribution_name(root)
        if normalized_root in parsed_requirements:
            continue

        local_candidate = _local_root_candidate_path(root, project_root)
        if local_candidate is None:
            continue

        offenders.append((root, local_candidate.relative_to(project_root).as_posix()))

    if not offenders:
        return

    offenders_display = ", ".join(
        f"{root} ({location})" for root, location in offenders
    )
    roots_display = ", ".join(sorted(first_party_roots))
    raise RuntimeError(
        "Imports look like local project code but are outside supported first-party roots: "
        f"{offenders_display}. Checked project root {project_root} and pinned requirements at "
        f"{requirements_path}. Move these modules under first-party roots ({roots_display}), "
        "or package them as third-party dependencies with pinned 'name==version' entries."
    )


def sync_dependency_cache(project_root: Path, build_dir: Path) -> tuple[Path, Path, dict[str, list[str]]]:
    """Install top-level deps once per build invocation and return lock + wheelhouse."""

    source_requirements = project_root / "requirements.txt"
    requirements_text = source_requirements.read_text(encoding="utf-8")
    cache_key = (
        str(project_root.resolve()),
        str(build_dir.resolve()),
        requirements_text,
    )

    deps_root = build_dir / DEPENDENCY_CACHE_DIRNAME
    deps_venv = deps_root / "venv"
    lock_path = deps_root / DEPENDENCY_LOCK_FILENAME
    wheelhouse = deps_root / "wheelhouse"

    with _DEPENDENCY_SYNC_LOCK:
        if cache_key in _DEPENDENCY_SYNC_CACHE and lock_path.exists() and wheelhouse.exists():
            package_map = _packages_distributions_from_python(deps_venv / "bin" / "python")
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
            ],
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
            ],
            "Failed to prepare local dependency wheelhouse",
        )

        package_map = _packages_distributions_from_python(deps_python)
        _DEPENDENCY_SYNC_CACHE.add(cache_key)
        return lock_path, wheelhouse, package_map


def prewarm_shared_build_state(
    project_root: Path,
    build_dir: Path,
    first_party_roots: set[str],
) -> SharedBuildState:
    """Compute reusable dependency and import analysis state once."""

    lock_requirements_path, wheelhouse, package_map = sync_dependency_cache(
        project_root=project_root,
        build_dir=build_dir,
    )
    analysis_cache = get_first_party_analysis_cache(project_root, first_party_roots)
    return SharedBuildState(
        lock_requirements_path=lock_requirements_path,
        wheelhouse=wheelhouse,
        package_map=package_map,
        analysis_cache=analysis_cache,
    )


def get_first_party_analysis_cache(
    project_root: Path,
    first_party_roots: set[str],
) -> FirstPartyAnalysisCache:
    """Return a reusable first-party import analysis cache for this process."""

    key = (str(project_root.resolve()), tuple(sorted(first_party_roots)))
    with _FIRST_PARTY_ANALYSIS_CACHE_LOCK:
        cached = _FIRST_PARTY_ANALYSIS_CACHE.get(key)
        if cached is not None:
            return cached

        cache = build_first_party_analysis_cache(
            project_root=project_root,
            first_party_roots=first_party_roots,
        )
        _FIRST_PARTY_ANALYSIS_CACHE[key] = cache
        return cache


def _packages_distributions_from_python(python_executable: Path) -> dict[str, list[str]]:
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


def _run_checked(command: list[str], failure_message: str) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode == 0:
        return completed

    raise RuntimeError(
        f"{failure_message}. "
        f"stdout:\n{completed.stdout}\n"
        f"stderr:\n{completed.stderr}"
    )


def build_debug_report(
    *,
    function_name: str,
    mode: str,
    verify: bool,
    run_tests: bool,
    build_target: Path,
    selected_modules: set[str],
    files_to_copy: set[Path],
    copied_tests_dir: Path | None,
    parsed_requirements: dict[str, str],
    package_map: dict[str, list[str]],
    per_function_requirements: list[str],
    first_party_roots: set[str],
    project_root: Path,
) -> str:
    import_roots = collect_import_roots(files_to_copy)
    if copied_tests_dir is not None and copied_tests_dir.exists():
        import_roots.update(collect_import_roots(set(copied_tests_dir.rglob("*.py"))))

    first_party_imports, stdlib_imports, third_party_imports = classify_roots(
        {root for root in import_roots},
        first_party_roots,
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
            third_party_resolution_lines.append(
                f"- {root}: local-outside-first-party ({location})"
            )
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
        f"[debug] Build report for '{function_name}'",
        f"  mode={mode} verify={verify} run_tests={run_tests}",
        f"  build_target={build_target}",
        f"  copied_first_party_files={len(files_to_copy)} selected_modules={len(selected_modules)}",
        "  import_roots="
        f"first_party:{len(first_party_imports)} stdlib:{len(stdlib_imports)} third_party:{len(third_party_imports)}",
        f"  copied_tests={tests_count}",
        f"  selected_requirements={len(per_function_requirements)}",
    ]

    if per_function_requirements:
        lines.append("  requirements:")
        lines.extend(f"    - {requirement}" for requirement in per_function_requirements)

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
