from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from monopack.build import (
    DEPENDENCY_LOCK_FILENAME,
    _pip_install_target,
    choose_auto_fix_target,
    create_build_artifact_zip,
    get_first_party_analysis_cache,
    normalize_sha_outputs,
    package_content_digest,
    parse_missing_module_from_traceback,
    prepare_source_requirements,
    persist_inline_config_fix,
    resolve_third_party_distributions,
    sync_dependency_cache,
    write_package_sha_file,
    write_package_sha_files,
)
from monopack.graph import build_first_party_analysis_cache
from monopack.inline_config import InlineConfig, parse_inline_config


class BuildTests(unittest.TestCase):
    def test_parse_missing_module_from_traceback_extracts_name(self):
        traceback_text = """
Build verification failed. stdout:\n\nstderr:
Traceback (most recent call last):
  File "_monopack_verify.py", line 1, in <module>
    import packs.users_get as target
ModuleNotFoundError: No module named 'app.hidden.runtime_dep'
"""

        self.assertEqual(
            parse_missing_module_from_traceback(traceback_text),
            "app.hidden.runtime_dep",
        )

    def test_parse_missing_module_from_traceback_returns_none_when_absent(self):
        self.assertIsNone(
            parse_missing_module_from_traceback("Build verification failed")
        )

    def test_choose_auto_fix_target_prefers_first_party_module(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / "app").mkdir()
            (project_root / "app" / "__init__.py").write_text("", encoding="utf-8")
            (project_root / "app" / "hidden.py").write_text("", encoding="utf-8")

            kind, value = choose_auto_fix_target(
                missing_module="app.hidden",
                project_root=project_root,
                packages_to_distributions={},
            )

        self.assertEqual((kind, value), ("module", "app.hidden"))

    def test_choose_auto_fix_target_uses_distribution_mapping_for_third_party(self):
        kind, value = choose_auto_fix_target(
            missing_module="yaml.loader",
            project_root=Path("/tmp/nonexistent"),
            packages_to_distributions={"yaml": ["PyYAML"]},
        )

        self.assertEqual((kind, value), ("distribution", "PyYAML"))

    def test_choose_auto_fix_target_deterministically_selects_first_sorted_distribution(
        self,
    ):
        kind, value = choose_auto_fix_target(
            missing_module="yaml.loader",
            project_root=Path("/tmp/nonexistent"),
            packages_to_distributions={
                "yaml": ["zeta-yaml", "PyYAML", "alpha-yaml"],
            },
        )

        self.assertEqual((kind, value), ("distribution", "alpha-yaml"))

    def test_resolve_third_party_distributions_maps_import_root_to_distribution(self):
        resolved = resolve_third_party_distributions(
            third_party_roots={"yaml"},
            parsed_requirements={"pyyaml": "PyYAML==6.0.2"},
            package_map={"yaml": ["PyYAML"]},
        )

        self.assertEqual(resolved, {"PyYAML"})

    def test_resolve_third_party_distributions_prefers_direct_requirement_match(self):
        resolved = resolve_third_party_distributions(
            third_party_roots={"requests"},
            parsed_requirements={"requests": "requests==2.32.3"},
            package_map={"requests": ["Requests"]},
        )

        self.assertEqual(resolved, {"requests"})

    def test_resolve_third_party_distributions_raises_for_unmapped_import(self):
        with self.assertRaisesRegex(
            KeyError,
            "Could not resolve imports to pinned third-party distributions",
        ):
            resolve_third_party_distributions(
                third_party_roots={"imaginarypkg"},
                parsed_requirements={"requests": "requests==2.32.3"},
                package_map={},
                project_root=Path("/tmp/project"),
                requirements_path=Path("/tmp/project/requirements.txt"),
            )

    def test_resolve_third_party_distributions_error_mentions_checked_paths(self):
        with self.assertRaisesRegex(
            KeyError,
            r"Checked local modules under /tmp/project and pinned lock requirements in /tmp/project/requirements.txt",
        ):
            resolve_third_party_distributions(
                third_party_roots={"imaginarypkg"},
                parsed_requirements={"requests": "requests==2.32.3"},
                package_map={},
                project_root=Path("/tmp/project"),
                requirements_path=Path("/tmp/project/requirements.txt"),
            )

    def test_resolve_third_party_distributions_selects_deterministic_candidate(self):
        resolved = resolve_third_party_distributions(
            third_party_roots={"yaml"},
            parsed_requirements={
                "alpha-yaml": "alpha-yaml==1.0.0",
                "pyyaml": "PyYAML==6.0.2",
            },
            package_map={"yaml": ["PyYAML", "alpha-yaml"]},
        )

        self.assertEqual(resolved, {"alpha-yaml"})

    def test_normalize_sha_outputs_defaults_to_hex(self):
        self.assertEqual(normalize_sha_outputs(None), {"hex"})
        self.assertEqual(normalize_sha_outputs(set()), {"hex"})

    def test_normalize_sha_outputs_rejects_unknown_values(self):
        with self.assertRaisesRegex(ValueError, "Unsupported sha output values"):
            normalize_sha_outputs({"md5"})

    def test_write_package_sha_files_writes_hex_and_b64(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            build_target = project_root / "build" / "users_get"
            build_target.mkdir(parents=True)
            (build_target / "packs").mkdir(parents=True)
            (build_target / "packs" / "users_get.py").write_text(
                "x = 1\n", encoding="utf-8"
            )
            (build_target / "requirements.txt").write_text(
                "requests==2.32.3\n", encoding="utf-8"
            )

            written = write_package_sha_files(
                build_target=build_target,
                output_prefix=project_root / "build" / "users_get",
                sha_outputs={"hex", "b64"},
            )

            self.assertEqual(len(written), 2)
            self.assertTrue(
                (project_root / "build" / "users_get.package.sha256").is_file()
            )
            self.assertTrue(
                (project_root / "build" / "users_get.package.sha256.b64").is_file()
            )

    def test_persist_inline_config_fix_preserves_non_managed_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entrypoint = Path(tmpdir) / "users_get.py"
            entrypoint.write_text(
                "\n".join(
                    [
                        '"""function doc"""',
                        "# monopack-start",
                        "# extra_modules: app.old.module",
                        "# extra_distributions:",
                        "# monopack-end",
                        "",
                        "import os",
                        "",
                        "def lambda_handler(event, context):",
                        "    return {'ok': True}",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            original = entrypoint.read_text(encoding="utf-8")
            config = parse_inline_config(original)
            updated = persist_inline_config_fix(
                entrypoint=entrypoint,
                config=config,
                target_kind="module",
                target_value="app.hidden.runtime_dep",
            )
            rewritten = entrypoint.read_text(encoding="utf-8")

            self.assertIn("app.hidden.runtime_dep", updated.extra_modules)
            rewritten_tail = rewritten[rewritten.index("import os") :]
            original_tail = original[original.index("import os") :]
            self.assertEqual(rewritten_tail, original_tail)

    def test_package_content_digest_is_stable_for_same_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            build_target = project_root / "build" / "users_get"
            build_target.mkdir(parents=True)
            (build_target / "packs").mkdir(parents=True)
            (build_target / "packs" / "users_get.py").write_text(
                "x = 1\n", encoding="utf-8"
            )
            (build_target / "requirements.txt").write_text(
                "requests==2.32.3\n", encoding="utf-8"
            )

            first = package_content_digest(build_target)
            second = package_content_digest(build_target)

            self.assertEqual(first, second)

    def test_persist_inline_config_fix_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entrypoint = Path(tmpdir) / "users_get.py"
            entrypoint.write_text(
                "def lambda_handler(event, context):\n    return {}\n",
                encoding="utf-8",
            )

            config = InlineConfig()
            updated = persist_inline_config_fix(
                entrypoint, config, "module", "app.hidden.runtime_dep"
            )
            persist_inline_config_fix(
                entrypoint, updated, "module", "app.hidden.runtime_dep"
            )

            parsed = parse_inline_config(entrypoint.read_text(encoding="utf-8"))

        self.assertEqual(parsed.extra_modules, {"app.hidden.runtime_dep"})

    def test_pip_install_target_raises_runtimeerror_with_stdout_and_stderr(self):
        completed = subprocess.CompletedProcess(
            args=["python", "-m", "pip", "install"],
            returncode=1,
            stdout="pip stdout details",
            stderr="pip stderr details",
        )

        with mock.patch("monopack.build.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(
                RuntimeError,
                r"Dependency installation failed\..*stdout:\n"
                r"pip stdout details\n"
                r"stderr:\n"
                r"pip stderr details",
            ):
                _pip_install_target(
                    Path("/tmp/build"), Path("/tmp/build/requirements.txt")
                )

    def test_pip_install_target_falls_back_to_pip_binary_when_module_missing(self):
        first = subprocess.CompletedProcess(
            args=["python", "-m", "pip", "install"],
            returncode=1,
            stdout="",
            stderr="No module named pip",
        )
        second = subprocess.CompletedProcess(
            args=["pip", "install"],
            returncode=0,
            stdout="ok",
            stderr="",
        )

        with mock.patch(
            "monopack.build.subprocess.run", side_effect=[first, second]
        ) as run:
            _pip_install_target(Path("/tmp/build"), Path("/tmp/build/requirements.txt"))

        self.assertEqual(run.call_count, 2)

    def test_pip_install_target_raises_clear_error_when_pip_unavailable(self):
        first = subprocess.CompletedProcess(
            args=["python", "-m", "pip", "install"],
            returncode=1,
            stdout="",
            stderr="No module named pip",
        )

        with mock.patch(
            "monopack.build.subprocess.run",
            side_effect=[first, FileNotFoundError("pip")],
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "neither 'python -m pip' nor 'pip' is available",
            ):
                _pip_install_target(
                    Path("/tmp/build"), Path("/tmp/build/requirements.txt")
                )

    def test_pip_install_target_retries_online_when_wheelhouse_install_fails(self):
        first = subprocess.CompletedProcess(
            args=["python", "-m", "pip", "install"],
            returncode=1,
            stdout="",
            stderr="No matching distribution found",
        )
        second = subprocess.CompletedProcess(
            args=["python", "-m", "pip", "install"],
            returncode=0,
            stdout="ok",
            stderr="",
        )

        with mock.patch(
            "monopack.build.subprocess.run", side_effect=[first, second]
        ) as run:
            _pip_install_target(
                Path("/tmp/build"),
                Path("/tmp/build/requirements.txt"),
                find_links=Path("/tmp/wheelhouse"),
                no_index=True,
            )

        self.assertEqual(run.call_count, 2)
        first_call = run.call_args_list[0].args[0]
        second_call = run.call_args_list[1].args[0]
        self.assertIn("--no-index", first_call)
        self.assertIn("--find-links", first_call)
        self.assertNotIn("--no-index", second_call)
        self.assertNotIn("--find-links", second_call)

    def test_prepare_source_requirements_uses_project_requirements_for_pip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            deps_root = project_root / "build" / ".deps"
            requirements_path = project_root / "requirements.txt"
            requirements_path.write_text("requests==2.32.3\n", encoding="utf-8")

            resolved = prepare_source_requirements(
                project_root=project_root,
                deps_root=deps_root,
                package_manager="pip",
            )

        self.assertEqual(resolved, requirements_path)

    def test_prepare_source_requirements_exports_from_poetry(self):
        completed = subprocess.CompletedProcess(
            args=["poetry", "export"],
            returncode=0,
            stdout="requests==2.32.3\n",
            stderr="",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            deps_root = project_root / "build" / ".deps"

            with mock.patch(
                "monopack.build.subprocess.run", return_value=completed
            ) as run:
                output_path = prepare_source_requirements(
                    project_root=project_root,
                    deps_root=deps_root,
                    package_manager="poetry",
                )

            self.assertTrue(output_path.is_file())
            self.assertEqual(
                output_path.read_text(encoding="utf-8"),
                "requests==2.32.3\n",
            )
            self.assertEqual(run.call_count, 1)

    def test_prepare_source_requirements_tries_fallback_export_command(self):
        first = subprocess.CompletedProcess(
            args=["uv", "export", "--format", "requirements.txt", "--no-hashes"],
            returncode=2,
            stdout="",
            stderr="unsupported format",
        )
        second = subprocess.CompletedProcess(
            args=["uv", "export", "--format", "requirements-txt", "--no-hashes"],
            returncode=0,
            stdout="requests==2.32.3\n",
            stderr="",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            deps_root = project_root / "build" / ".deps"

            with mock.patch(
                "monopack.build.subprocess.run", side_effect=[first, second]
            ) as run:
                output_path = prepare_source_requirements(
                    project_root=project_root,
                    deps_root=deps_root,
                    package_manager="uv",
                )

            self.assertEqual(run.call_count, 2)
            self.assertEqual(
                output_path.read_text(encoding="utf-8"),
                "requests==2.32.3\n",
            )

    def test_prepare_source_requirements_raises_when_export_fails(self):
        failed = subprocess.CompletedProcess(
            args=["pipenv", "requirements"],
            returncode=1,
            stdout="",
            stderr="pipenv command failed",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            deps_root = project_root / "build" / ".deps"

            with mock.patch("monopack.build.subprocess.run", return_value=failed):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "Failed to export requirements from package manager 'pipenv'",
                ):
                    prepare_source_requirements(
                        project_root=project_root,
                        deps_root=deps_root,
                        package_manager="pipenv",
                    )

    def test_sync_dependency_cache_accepts_unpinned_source_and_writes_pinned_lock(self):
        freeze_stdout = "requests==2.32.3\nidna==3.11\n"

        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            build_dir = project_root / "build"
            project_root.mkdir(parents=True)
            (project_root / "requirements.txt").write_text(
                "requests>=2\n",
                encoding="utf-8",
            )

            run_checked_results = [
                subprocess.CompletedProcess(
                    args=["venv"], returncode=0, stdout="", stderr=""
                ),
                subprocess.CompletedProcess(
                    args=["install"], returncode=0, stdout="", stderr=""
                ),
                subprocess.CompletedProcess(
                    args=["freeze"], returncode=0, stdout=freeze_stdout, stderr=""
                ),
                subprocess.CompletedProcess(
                    args=["download"], returncode=0, stdout="", stderr=""
                ),
            ]

            with mock.patch(
                "monopack.build._run_checked",
                side_effect=run_checked_results,
            ) as run_checked:
                with mock.patch(
                    "monopack.build._packages_distributions_from_python",
                    return_value={"requests": ["requests"]},
                ):
                    lock_path, wheelhouse, package_map = sync_dependency_cache(
                        project_root=project_root,
                        build_dir=build_dir,
                        package_manager="auto",
                    )

            self.assertTrue(lock_path.is_file())
            self.assertEqual(lock_path.name, DEPENDENCY_LOCK_FILENAME)
            self.assertEqual(lock_path.read_text(encoding="utf-8"), freeze_stdout)
            self.assertTrue(wheelhouse.is_dir())
            self.assertEqual(package_map, {"requests": ["requests"]})

            install_command = run_checked.call_args_list[1].args[0]
            self.assertIn("-r", install_command)
            self.assertIn(str(project_root / "requirements.txt"), install_command)

    def test_sync_dependency_cache_auto_detects_uv_for_source_requirements(self):
        freeze_stdout = "requests==2.32.3\n"

        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            build_dir = project_root / "build"
            deps_root = build_dir / ".deps"
            source_requirements = deps_root / "uv.requirements.txt"

            project_root.mkdir(parents=True)
            (project_root / "uv.lock").write_text("", encoding="utf-8")
            deps_root.mkdir(parents=True, exist_ok=True)
            source_requirements.write_text("requests>=2\n", encoding="utf-8")

            run_checked_results = [
                subprocess.CompletedProcess(
                    args=["venv"], returncode=0, stdout="", stderr=""
                ),
                subprocess.CompletedProcess(
                    args=["install"], returncode=0, stdout="", stderr=""
                ),
                subprocess.CompletedProcess(
                    args=["freeze"], returncode=0, stdout=freeze_stdout, stderr=""
                ),
                subprocess.CompletedProcess(
                    args=["download"], returncode=0, stdout="", stderr=""
                ),
            ]

            with mock.patch(
                "monopack.build.prepare_source_requirements",
                return_value=source_requirements,
            ) as prepare:
                with mock.patch(
                    "monopack.build._run_checked",
                    side_effect=run_checked_results,
                ):
                    with mock.patch(
                        "monopack.build._packages_distributions_from_python",
                        return_value={"requests": ["requests"]},
                    ):
                        sync_dependency_cache(
                            project_root=project_root,
                            build_dir=build_dir,
                            package_manager="auto",
                        )

            self.assertEqual(
                prepare.call_args.kwargs["package_manager"],
                "uv",
            )

    def test_sync_dependency_cache_reuses_discovered_pip_cache_when_available(self):
        freeze_stdout = "requests==2.32.3\n"

        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            build_dir = project_root / "build"
            project_root.mkdir(parents=True)
            (project_root / "requirements.txt").write_text(
                "requests>=2\n",
                encoding="utf-8",
            )

            run_checked_results = [
                subprocess.CompletedProcess(
                    args=["venv"], returncode=0, stdout="", stderr=""
                ),
                subprocess.CompletedProcess(
                    args=["install"], returncode=0, stdout="", stderr=""
                ),
                subprocess.CompletedProcess(
                    args=["freeze"], returncode=0, stdout=freeze_stdout, stderr=""
                ),
                subprocess.CompletedProcess(
                    args=["download"], returncode=0, stdout="", stderr=""
                ),
            ]

            with mock.patch(
                "monopack.build._discover_existing_install_python",
                return_value=(
                    Path("/seed/.venv/bin/python"),
                    "project:.venv/bin/python",
                ),
            ):
                with mock.patch(
                    "monopack.build._pip_cache_dir_for_python",
                    return_value=Path("/seed/pip-cache"),
                ):
                    with mock.patch(
                        "monopack.build._run_checked",
                        side_effect=run_checked_results,
                    ) as run_checked:
                        with mock.patch(
                            "monopack.build._packages_distributions_from_python",
                            return_value={"requests": ["requests"]},
                        ):
                            sync_dependency_cache(
                                project_root=project_root,
                                build_dir=build_dir,
                                package_manager="auto",
                                existing_install_python=".venv/bin/python",
                            )

            install_command = run_checked.call_args_list[1].args[0]
            download_command = run_checked.call_args_list[3].args[0]
            self.assertIn("--cache-dir", install_command)
            self.assertIn("/seed/pip-cache", install_command)
            self.assertIn("--cache-dir", download_command)
            self.assertIn("/seed/pip-cache", download_command)

    def test_sync_dependency_cache_prints_when_no_existing_install_cache_found(self):
        freeze_stdout = "requests==2.32.3\n"

        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            build_dir = project_root / "build"
            project_root.mkdir(parents=True)
            (project_root / "requirements.txt").write_text(
                "requests>=2\n",
                encoding="utf-8",
            )

            run_checked_results = [
                subprocess.CompletedProcess(
                    args=["venv"], returncode=0, stdout="", stderr=""
                ),
                subprocess.CompletedProcess(
                    args=["install"], returncode=0, stdout="", stderr=""
                ),
                subprocess.CompletedProcess(
                    args=["freeze"], returncode=0, stdout=freeze_stdout, stderr=""
                ),
                subprocess.CompletedProcess(
                    args=["download"], returncode=0, stdout="", stderr=""
                ),
            ]

            with mock.patch(
                "monopack.build._discover_existing_install_python",
                return_value=(None, "no install candidate found"),
            ):
                with mock.patch(
                    "monopack.build._run_checked",
                    side_effect=run_checked_results,
                ):
                    with mock.patch(
                        "monopack.build._packages_distributions_from_python",
                        return_value={"requests": ["requests"]},
                    ):
                        with mock.patch("builtins.print") as print_mock:
                            sync_dependency_cache(
                                project_root=project_root,
                                build_dir=build_dir,
                                package_manager="auto",
                                existing_install_python=".venv/bin/python",
                            )

            messages = [call.args[0] for call in print_mock.call_args_list]
            self.assertIn(
                "[build] No existing install cache found; using normal dependency cache sync.",
                messages,
            )

    def test_create_build_artifact_zip_writes_files_with_sorted_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            build_target = project_root / "build" / "users_get"
            artifact_path = project_root / "build" / "users_get.zip"
            (build_target / "zeta").mkdir(parents=True)
            (build_target / "alpha").mkdir(parents=True)
            (build_target / "zeta" / "file.txt").write_text("zeta\n", encoding="utf-8")
            (build_target / "alpha" / "file.txt").write_text(
                "alpha\n", encoding="utf-8"
            )

            result = create_build_artifact_zip(build_target, artifact_path)

            self.assertEqual(result, artifact_path)
            with zipfile.ZipFile(artifact_path) as archive:
                names = archive.namelist()
                self.assertEqual(names, ["alpha/file.txt", "zeta/file.txt"])
                self.assertEqual(archive.read("alpha/file.txt"), b"alpha\n")
                self.assertEqual(archive.read("zeta/file.txt"), b"zeta\n")

    def test_create_build_artifact_zip_writes_expected_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            build_target = project_root / "build" / "users_get"
            artifact_path = project_root / "build" / "users_get.zip"
            build_target.mkdir(parents=True)
            (build_target / "handler.py").write_text("x = 1\n", encoding="utf-8")

            create_build_artifact_zip(build_target, artifact_path)

            with zipfile.ZipFile(artifact_path) as archive:
                self.assertEqual(archive.read("handler.py"), b"x = 1\n")

    def test_write_package_sha_file_is_stable_for_same_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            build_target = project_root / "build" / "users_get"
            build_target.mkdir(parents=True)
            (build_target / "packs").mkdir(parents=True)
            (build_target / "packs" / "users_get.py").write_text(
                "x = 1\n", encoding="utf-8"
            )
            (build_target / "requirements.txt").write_text(
                "requests==2.32.3\n", encoding="utf-8"
            )
            (build_target / "requests").mkdir(parents=True)
            (build_target / "requests" / "__init__.py").write_text(
                "__version__='x'\n", encoding="utf-8"
            )

            first = write_package_sha_file(
                build_target, project_root / "build" / "users_get.package.sha256"
            )
            second = write_package_sha_file(
                build_target, project_root / "build" / "users_get.package.sha256"
            )

            self.assertEqual(
                first.read_text(encoding="utf-8"), second.read_text(encoding="utf-8")
            )

    def test_write_package_sha_file_changes_when_first_party_content_changes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            build_target = project_root / "build" / "users_get"
            build_target.mkdir(parents=True)
            (build_target / "packs").mkdir(parents=True)
            source_file = build_target / "packs" / "users_get.py"
            source_file.write_text("x = 1\n", encoding="utf-8")
            (build_target / "requirements.txt").write_text(
                "requests==2.32.3\n", encoding="utf-8"
            )

            output_path = project_root / "build" / "users_get.package.sha256"
            write_package_sha_file(build_target, output_path)
            before = output_path.read_text(encoding="utf-8")

            source_file.write_text("x = 2\n", encoding="utf-8")
            write_package_sha_file(build_target, output_path)
            after = output_path.read_text(encoding="utf-8")

            self.assertNotEqual(before, after)

    def test_get_first_party_analysis_cache_reuses_single_process_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            entrypoint = project_root / "packs" / "users_get.py"
            entrypoint.parent.mkdir(parents=True)
            entrypoint.write_text("import app.users.service\n", encoding="utf-8")
            service_file = project_root / "app" / "users" / "service.py"
            service_file.parent.mkdir(parents=True)
            service_file.write_text("VALUE = 1\n", encoding="utf-8")

            with mock.patch(
                "monopack.build.build_first_party_analysis_cache",
                wraps=build_first_party_analysis_cache,
            ) as build_cache:
                first = get_first_party_analysis_cache(project_root)
                second = get_first_party_analysis_cache(project_root)

            self.assertIs(first, second)
            self.assertEqual(build_cache.call_count, 1)

    def test_get_first_party_analysis_cache_invalidates_when_runtime_files_change(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            entrypoint = project_root / "packs" / "users_get.py"
            entrypoint.parent.mkdir(parents=True)
            entrypoint.write_text("import app.users.service\n", encoding="utf-8")
            service_file = project_root / "app" / "users" / "service.py"
            service_file.parent.mkdir(parents=True)
            service_file.write_text("VALUE = 1\n", encoding="utf-8")

            with mock.patch(
                "monopack.build.build_first_party_analysis_cache",
                wraps=build_first_party_analysis_cache,
            ) as build_cache:
                first = get_first_party_analysis_cache(project_root)
                service_file.write_text("VALUE = 100\n", encoding="utf-8")
                second = get_first_party_analysis_cache(project_root)

            self.assertIsNot(first, second)
            self.assertEqual(build_cache.call_count, 2)


if __name__ == "__main__":
    unittest.main()
