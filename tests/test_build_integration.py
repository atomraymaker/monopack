import sys
from pathlib import Path
import unittest
from unittest import mock
import zipfile


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from monopack.build import build_function
from monopack.cli import main as cli_main
from monopack.inline_config import parse_inline_config
from helpers import assert_files_exist, assert_paths_not_exist, fixture_project, run_cli_captured


class BuildIntegrationTests(unittest.TestCase):
    def test_build_function_creates_expected_files(self):
        with fixture_project("simple") as project_root:

            build_target = build_function(
                function_name="users_get",
                functions_dir=project_root / "functions",
                build_dir=project_root / "build",
                project_root=project_root,
                verify=True,
            )

            self.assertEqual(build_target, project_root / "build" / "users_get")
            assert_files_exist(
                self,
                build_target,
                [
                    "functions/users_get.py",
                    "_monopack_verify.py",
                ],
            )
            artifact_path = project_root / "build" / "users_get.zip"
            package_sha_path = project_root / "build" / "users_get.package.sha256"
            self.assertTrue(artifact_path.is_file())
            self.assertTrue(package_sha_path.is_file())
            self.assertRegex(package_sha_path.read_text(encoding="utf-8"), r"^[0-9a-f]{64}\n$")
            with zipfile.ZipFile(artifact_path) as archive:
                names = archive.namelist()
                self.assertIn("functions/users_get.py", names)
                self.assertNotIn("requirements.txt", names)
                self.assertFalse(any(name.startswith("build/") for name in names))

    def test_build_function_writes_b64_package_sha_when_requested(self):
        with fixture_project("simple") as project_root:

            build_target = build_function(
                function_name="users_get",
                functions_dir=project_root / "functions",
                build_dir=project_root / "build",
                project_root=project_root,
                verify=True,
                sha_outputs={"hex", "b64"},
            )

            self.assertEqual(build_target, project_root / "build" / "users_get")
            self.assertTrue((project_root / "build" / "users_get.package.sha256").is_file())
            b64_path = project_root / "build" / "users_get.package.sha256.b64"
            self.assertTrue(b64_path.is_file())
            self.assertRegex(b64_path.read_text(encoding="utf-8"), r"^[A-Za-z0-9+/]+=*\n$")

    def test_cli_build_path_creates_expected_files(self):
        with fixture_project("simple") as project_root:
            result, _, stderr = run_cli_captured(
                cli_main,
                [
                    "users_get",
                    "--functions-dir",
                    str(project_root / "functions"),
                    "--build-dir",
                    str(project_root / "build"),
                    "--verify",
                ],
            )

            build_target = project_root / "build" / "users_get"
            self.assertEqual(result, 0)
            assert_files_exist(
                self,
                build_target,
                [
                    "functions/users_get.py",
                    "_monopack_verify.py",
                ],
            )
            artifact_path = project_root / "build" / "users_get.zip"
            self.assertTrue(artifact_path.is_file())
            with zipfile.ZipFile(artifact_path) as archive:
                names = archive.namelist()
                self.assertIn("functions/users_get.py", names)
                self.assertNotIn("requirements.txt", names)
                self.assertFalse(any(name.startswith("build/") for name in names))
            self.assertEqual(stderr, "")

    def test_build_function_test_mode_does_not_create_zip(self):
        with fixture_project("test_mode") as project_root:
            with mock.patch("monopack.build._pip_install_target"):
                build_function(
                    function_name="users_get",
                    functions_dir=project_root / "functions",
                    build_dir=project_root / "build",
                    project_root=project_root,
                    verify=False,
                    mode="test",
                )

            self.assertFalse((project_root / "build" / "users_get.zip").exists())

    def test_build_function_copies_reachable_first_party_modules(self):
        with fixture_project("shared_code") as project_root:

            build_target = build_function(
                function_name="users_get",
                functions_dir=project_root / "functions",
                build_dir=project_root / "build",
                project_root=project_root,
                verify=True,
            )

            expected_paths = [
                "functions/__init__.py",
                "functions/users_get.py",
                "app/__init__.py",
                "app/users/__init__.py",
                "app/users/service.py",
                "app/shared/__init__.py",
                "app/shared/auth.py",
                "_monopack_verify.py",
            ]

            assert_files_exist(self, build_target, expected_paths)

    def test_build_function_triggers_pip_install_for_third_party_requirements(self):
        with fixture_project("third_party") as project_root:

            with mock.patch("monopack.build._pip_install_target") as pip_install:
                build_target = build_function(
                    function_name="users_get",
                    functions_dir=project_root / "functions",
                    build_dir=project_root / "build",
                    project_root=project_root,
                    verify=False,
                )

            assert_files_exist(
                self,
                build_target,
                [
                    "functions/users_get.py",
                    "requirements.txt",
                    "_monopack_verify.py",
                ],
            )
            self.assertEqual(
                (build_target / "requirements.txt").read_text(encoding="utf-8"),
                "requests==2.32.3\n",
            )
            pip_install.assert_called_once_with(
                build_target,
                build_target / "requirements.txt",
                find_links=project_root / "build" / ".deps" / "wheelhouse",
                no_index=True,
            )

    def test_build_function_copies_modules_discovered_via_relative_imports(self):
        with fixture_project("relative_imports") as project_root:

            build_target = build_function(
                function_name="users_get",
                functions_dir=project_root / "functions",
                build_dir=project_root / "build",
                project_root=project_root,
                verify=True,
            )

            expected_paths = [
                "functions/__init__.py",
                "functions/users_get.py",
                "app/__init__.py",
                "app/handlers/__init__.py",
                "app/handlers/user_handler.py",
                "app/services/__init__.py",
                "app/services/users.py",
                "app/services/profile.py",
                "app/shared/__init__.py",
                "app/shared/auth.py",
                "app/shared/tokens.py",
                "_monopack_verify.py",
            ]

            assert_files_exist(self, build_target, expected_paths)

    def test_build_function_handles_first_party_cycles(self):
        with fixture_project("cycles") as project_root:

            build_target = build_function(
                function_name="users_get",
                functions_dir=project_root / "functions",
                build_dir=project_root / "build",
                project_root=project_root,
                verify=True,
            )

            assert_files_exist(self, build_target, ["app/cycle/alpha.py", "app/cycle/beta.py"])

    def test_build_function_resolves_submodule_from_from_import(self):
        with fixture_project("from_import_submodule") as project_root:

            build_target = build_function(
                function_name="users_get",
                functions_dir=project_root / "functions",
                build_dir=project_root / "build",
                project_root=project_root,
                verify=True,
            )

            assert_files_exist(
                self,
                build_target,
                [
                    "functions/users_get.py",
                    "app/users/service.py",
                    "app/shared/auth.py",
                    "_monopack_verify.py",
                ],
            )

    def test_build_function_ignores_type_checking_imports_for_graph_and_requirements(self):
        with fixture_project("type_checking_imports") as project_root:

            build_target = build_function(
                function_name="users_get",
                functions_dir=project_root / "functions",
                build_dir=project_root / "build",
                project_root=project_root,
                verify=True,
            )

            assert_files_exist(
                self,
                build_target,
                [
                    "functions/users_get.py",
                    "app/users/service.py",
                    "_monopack_verify.py",
                ],
            )
            assert_paths_not_exist(self, build_target, ["app/shared/schema.py"])
            self.assertFalse((build_target / "requirements.txt").exists())

    def test_build_function_includes_transitive_third_party_requirements(self):
        with fixture_project("transitive_deps") as project_root:

            with mock.patch("monopack.build._pip_install_target"):
                build_target = build_function(
                    function_name="users_get",
                    functions_dir=project_root / "functions",
                    build_dir=project_root / "build",
                    project_root=project_root,
                    verify=False,
                )

            self.assertEqual(
                (build_target / "requirements.txt").read_text(encoding="utf-8"),
                "requests==2.32.3\n",
            )

    def test_deploy_mode_does_not_copy_tests_directory(self):
        with fixture_project("test_mode") as project_root:

            with mock.patch("monopack.build._pip_install_target"):
                build_target = build_function(
                    function_name="users_get",
                    functions_dir=project_root / "functions",
                    build_dir=project_root / "build",
                    project_root=project_root,
                    verify=False,
                    mode="deploy",
                )

            assert_paths_not_exist(self, build_target, ["tests"])

    def test_test_mode_copies_tests_directory(self):
        with fixture_project("test_mode") as project_root:

            with mock.patch("monopack.build._pip_install_target"):
                build_target = build_function(
                    function_name="users_get",
                    functions_dir=project_root / "functions",
                    build_dir=project_root / "build",
                    project_root=project_root,
                    verify=False,
                    mode="test",
                )

            assert_files_exist(self, build_target, ["tests/test_users.py"])

    def test_test_mode_includes_runtime_and_test_only_requirements(self):
        with fixture_project("test_mode") as project_root:

            with mock.patch("monopack.build._pip_install_target"):
                build_target = build_function(
                    function_name="users_get",
                    functions_dir=project_root / "functions",
                    build_dir=project_root / "build",
                    project_root=project_root,
                    verify=False,
                    mode="test",
                )

            self.assertEqual(
                (build_target / "requirements.txt").read_text(encoding="utf-8"),
                "colorama==0.4.6\nrequests==2.32.3\n",
            )

    def test_test_mode_verify_runs_unittest_discovery(self):
        with fixture_project("test_mode") as project_root:

            with mock.patch("monopack.build._pip_install_target"), mock.patch(
                "monopack.build.run_verifier_script"
            ) as run_verifier, mock.patch(
                "monopack.build.run_unittest_discovery"
            ) as run_unittests:
                build_target = build_function(
                    function_name="users_get",
                    functions_dir=project_root / "functions",
                    build_dir=project_root / "build",
                    project_root=project_root,
                    verify=True,
                    mode="test",
                )

            run_verifier.assert_called_once()
            run_unittests.assert_called_once_with(build_target / "tests", cwd=build_target)

    def test_test_mode_fails_when_no_relevant_tests_exist(self):
        with fixture_project("kitchen_sink") as project_root:
            with self.assertRaisesRegex(
                RuntimeError,
                r"No relevant tests were copied for function 'reports_refresh'",
            ):
                build_function(
                    function_name="reports_refresh",
                    functions_dir=project_root / "functions",
                    build_dir=project_root / "build",
                    project_root=project_root,
                    verify=False,
                    mode="test",
                )

    def test_test_mode_passes_when_relevant_tests_exist(self):
        with fixture_project("kitchen_sink") as project_root:
            with mock.patch("monopack.build._pip_install_target"):
                build_target = build_function(
                    function_name="users_get",
                    functions_dir=project_root / "functions",
                    build_dir=project_root / "build",
                    project_root=project_root,
                    verify=False,
                    mode="test",
                )

            assert_files_exist(self, build_target, ["tests/users/test_users_get.py"])

    def test_deploy_with_tests_runs_and_strips_tests_before_zip(self):
        with fixture_project("test_mode") as project_root:
            with mock.patch("monopack.build._pip_install_target"), mock.patch(
                "monopack.build.run_verifier_script"
            ) as run_verifier, mock.patch(
                "monopack.build.run_unittest_discovery"
            ) as run_unittests:
                build_target = build_function(
                    function_name="users_get",
                    functions_dir=project_root / "functions",
                    build_dir=project_root / "build",
                    project_root=project_root,
                    verify=True,
                    mode="deploy",
                    with_tests=True,
                )

            run_verifier.assert_called_once()
            run_unittests.assert_called_once_with(build_target / "tests", cwd=build_target)
            assert_paths_not_exist(self, build_target, ["tests"])
            artifact_path = project_root / "build" / "users_get.zip"
            self.assertTrue(artifact_path.is_file())
            with zipfile.ZipFile(artifact_path) as archive:
                names = archive.namelist()
                self.assertNotIn("tests/test_users.py", names)
                self.assertIn("functions/users_get.py", names)

    def test_test_mode_monorepo_split_users_includes_only_users_tests(self):
        with fixture_project("monorepo_split") as project_root:

            with mock.patch("monopack.build._pip_install_target"):
                build_target = build_function(
                    function_name="users_get",
                    functions_dir=project_root / "functions",
                    build_dir=project_root / "build",
                    project_root=project_root,
                    verify=False,
                    mode="test",
                )

            assert_files_exist(
                self,
                build_target,
                [
                    "tests/__init__.py",
                    "tests/users/__init__.py",
                    "tests/users/test_users_get.py",
                ],
            )
            assert_paths_not_exist(
                self,
                build_target,
                [
                    "tests/billing/test_billing_charge.py",
                    "tests/shared/test_unrelated.py",
                ],
            )

    def test_test_mode_monorepo_split_billing_includes_only_billing_tests(self):
        with fixture_project("monorepo_split") as project_root:

            with mock.patch("monopack.build._pip_install_target"):
                build_target = build_function(
                    function_name="billing_charge",
                    functions_dir=project_root / "functions",
                    build_dir=project_root / "build",
                    project_root=project_root,
                    verify=False,
                    mode="test",
                )

            assert_files_exist(
                self,
                build_target,
                [
                    "tests/__init__.py",
                    "tests/billing/__init__.py",
                    "tests/billing/test_billing_charge.py",
                ],
            )
            assert_paths_not_exist(
                self,
                build_target,
                [
                    "tests/users/test_users_get.py",
                    "tests/shared/test_unrelated.py",
                ],
            )

    def test_test_mode_monorepo_split_scopes_test_only_requirements_per_function(self):
        with fixture_project("monorepo_split") as project_root:

            with mock.patch("monopack.build._pip_install_target"):
                users_build_target = build_function(
                    function_name="users_get",
                    functions_dir=project_root / "functions",
                    build_dir=project_root / "build",
                    project_root=project_root,
                    verify=False,
                    mode="test",
                )

                billing_build_target = build_function(
                    function_name="billing_charge",
                    functions_dir=project_root / "functions",
                    build_dir=project_root / "build",
                    project_root=project_root,
                    verify=False,
                    mode="test",
                )

            self.assertEqual(
                (users_build_target / "requirements.txt").read_text(encoding="utf-8"),
                "colorama==0.4.6\nrequests==2.32.3\n",
            )
            self.assertEqual(
                (billing_build_target / "requirements.txt").read_text(encoding="utf-8"),
                "idna==3.10\n",
            )

    def test_build_function_applies_inline_config_overrides(self):
        with fixture_project("config_overrides") as project_root:

            with mock.patch("monopack.build._pip_install_target"):
                build_target = build_function(
                    function_name="users_get",
                    functions_dir=project_root / "functions",
                    build_dir=project_root / "build",
                    project_root=project_root,
                    verify=False,
                )

            assert_files_exist(self, build_target, ["app/hidden/runtime_dep.py"])
            self.assertEqual(
                (build_target / "requirements.txt").read_text(encoding="utf-8"),
                "PyYAML==6.0.2\n",
            )

    def test_build_function_resolves_literal_dynamic_imports_without_auto_fix(self):
        with fixture_project("dynamic_literal_imports") as project_root:
            entrypoint = project_root / "functions" / "users_get.py"
            original_source = entrypoint.read_text(encoding="utf-8")

            def fake_pip_install(build_target: Path, requirements_path: Path, **_kwargs) -> None:
                self.assertEqual(
                    requirements_path.read_text(encoding="utf-8"),
                    "idna==3.10\n",
                )
                (build_target / "idna.py").write_text("__version__ = '3.10'\n", encoding="utf-8")

            with mock.patch("monopack.build._pip_install_target", side_effect=fake_pip_install) as pip_install:
                build_target = build_function(
                    function_name="users_get",
                    functions_dir=project_root / "functions",
                    build_dir=project_root / "build",
                    project_root=project_root,
                    verify=True,
                )

            assert_files_exist(
                self,
                build_target,
                [
                    "functions/users_get.py",
                    "app/hidden/runtime_dep.py",
                    "idna.py",
                    "_monopack_verify.py",
                    "requirements.txt",
                ],
            )
            self.assertEqual(
                (build_target / "requirements.txt").read_text(encoding="utf-8"),
                "idna==3.10\n",
            )
            self.assertEqual(entrypoint.read_text(encoding="utf-8"), original_source)
            pip_install.assert_called_once()

    def test_build_function_auto_fix_first_party_updates_entrypoint_and_succeeds(self):
        with fixture_project("auto_fix_first_party") as project_root:
            entrypoint = project_root / "functions" / "users_get.py"

            build_target = build_function(
                function_name="users_get",
                functions_dir=project_root / "functions",
                build_dir=project_root / "build",
                project_root=project_root,
                verify=True,
                auto_fix=True,
            )

            rewritten = entrypoint.read_text(encoding="utf-8")

            assert_files_exist(self, build_target, ["app/hidden/runtime_dep.py"])
            self.assertIn("# monopack-start\n", rewritten)
            self.assertIn("# extra_modules: app.hidden.runtime_dep\n", rewritten)

    def test_build_function_auto_fix_handles_missing_module_from_tests(self):
        with fixture_project("kitchen_sink") as project_root:
            entrypoint = project_root / "functions" / "users_get.py"
            (project_root / "app" / "hidden").mkdir(parents=True, exist_ok=True)
            (project_root / "app" / "hidden" / "__init__.py").write_text("", encoding="utf-8")
            (project_root / "app" / "hidden" / "runtime_dep.py").write_text(
                "def marker():\n    return 'ok'\n",
                encoding="utf-8",
            )

            test_failure = RuntimeError(
                "Test discovery failed. stdout:\n\nstderr:\n"
                "Traceback (most recent call last):\n"
                "ModuleNotFoundError: No module named 'app.hidden.runtime_dep'\n"
            )

            with mock.patch("monopack.build.run_verifier_script", return_value=None), mock.patch(
                "monopack.build.run_unittest_discovery",
                side_effect=[test_failure, None],
            ) as run_unittests, mock.patch("monopack.build._pip_install_target"):
                build_function(
                    function_name="users_get",
                    functions_dir=project_root / "functions",
                    build_dir=project_root / "build",
                    project_root=project_root,
                    verify=True,
                    auto_fix=True,
                    with_tests=True,
                )

            rewritten = entrypoint.read_text(encoding="utf-8")
            parsed = parse_inline_config(rewritten)
            self.assertIn("# monopack-start\n", rewritten)
            self.assertIn("app.hidden.runtime_dep", parsed.extra_modules)
            self.assertEqual(run_unittests.call_count, 2)

    def test_build_function_auto_fix_third_party_adds_distribution_and_requirements(self):
        with fixture_project("auto_fix_third_party") as project_root:
            entrypoint = project_root / "functions" / "users_get.py"

            def fake_pip_install(build_target: Path, requirements_path: Path, **_kwargs) -> None:
                self.assertEqual(
                    requirements_path.read_text(encoding="utf-8"),
                    "requests==2.32.3\n",
                )
                (build_target / "requests.py").write_text(
                    "__version__ = '2.32.3'\n",
                    encoding="utf-8",
                )

            with mock.patch("monopack.build._pip_install_target", side_effect=fake_pip_install) as pip_install:
                build_target = build_function(
                    function_name="users_get",
                    functions_dir=project_root / "functions",
                    build_dir=project_root / "build",
                    project_root=project_root,
                    verify=True,
                    auto_fix=True,
                )

            rewritten = entrypoint.read_text(encoding="utf-8")
            parsed = parse_inline_config(rewritten)
            assert_files_exist(self, build_target, ["requests.py"])
            self.assertEqual(
                (build_target / "requirements.txt").read_text(encoding="utf-8"),
                "requests==2.32.3\n",
            )
            self.assertIn("requests", {name.lower() for name in parsed.extra_distributions})
            pip_install.assert_called_once()

    def test_build_function_auto_fix_distribution_aliases_use_mapped_names(self):
        with fixture_project("distribution_aliases") as project_root:
            entrypoint = project_root / "functions" / "users_get.py"

            def fake_pip_install(build_target: Path, requirements_path: Path, **_kwargs) -> None:
                requirements_text = requirements_path.read_text(encoding="utf-8")
                if "PyYAML==6.0.2\n" in requirements_text:
                    (build_target / "yaml.py").write_text(
                        "__version__ = '6.0.2'\n",
                        encoding="utf-8",
                    )
                if "python-dateutil==2.9.0.post0\n" in requirements_text:
                    dateutil_dir = build_target / "dateutil"
                    dateutil_dir.mkdir(exist_ok=True)
                    (dateutil_dir / "__init__.py").write_text("", encoding="utf-8")
                    (dateutil_dir / "parser.py").write_text(
                        "def parse(value):\n    return value\n",
                        encoding="utf-8",
                    )

            def verification_error(module_name: str) -> RuntimeError:
                return RuntimeError(
                    "Build verification failed. stdout:\n\nstderr:\n"
                    "Traceback (most recent call last):\n"
                    f"ModuleNotFoundError: No module named '{module_name}'\n"
                )

            with mock.patch(
                "monopack.build.packages_distributions",
                return_value={
                    "yaml": ["PyYAML"],
                    "dateutil": ["python-dateutil"],
                },
            ), mock.patch(
                "monopack.build._pip_install_target",
                side_effect=fake_pip_install,
            ), mock.patch(
                "monopack.build.run_verifier_script",
                side_effect=[
                    verification_error("yaml"),
                    verification_error("dateutil"),
                    None,
                ],
            ) as pip_install:
                build_target = build_function(
                    function_name="users_get",
                    functions_dir=project_root / "functions",
                    build_dir=project_root / "build",
                    project_root=project_root,
                    verify=True,
                    auto_fix=True,
                )

            parsed = parse_inline_config(entrypoint.read_text(encoding="utf-8"))

            self.assertEqual(parsed.extra_distributions, {"PyYAML", "python-dateutil"})
            self.assertEqual(
                (build_target / "requirements.txt").read_text(encoding="utf-8"),
                "PyYAML==6.0.2\npython-dateutil==2.9.0.post0\n",
            )
            self.assertGreaterEqual(pip_install.call_count, 2)

    def test_kitchen_sink_users_test_mode_scopes_tests_and_requirements(self):
        with fixture_project("kitchen_sink") as project_root:

            with mock.patch("monopack.build._pip_install_target"):
                build_target = build_function(
                    function_name="users_get",
                    functions_dir=project_root / "functions",
                    build_dir=project_root / "build",
                    project_root=project_root,
                    verify=False,
                    mode="test",
                )

            assert_files_exist(
                self,
                build_target,
                ["tests/users/test_users_get.py", "app/shared/runtime_flags.py"],
            )
            assert_paths_not_exist(
                self,
                build_target,
                [
                    "tests/billing/test_billing_charge.py",
                    "tests/shared/test_unrelated.py",
                ],
            )
            self.assertEqual(
                (build_target / "requirements.txt").read_text(encoding="utf-8"),
                "colorama==0.4.6\nrequests==2.32.3\n",
            )

    def test_kitchen_sink_billing_deploy_mode_excludes_tests(self):
        with fixture_project("kitchen_sink") as project_root:

            with mock.patch("monopack.build._pip_install_target"):
                build_target = build_function(
                    function_name="billing_charge",
                    functions_dir=project_root / "functions",
                    build_dir=project_root / "build",
                    project_root=project_root,
                    verify=False,
                    mode="deploy",
                )

            assert_paths_not_exist(self, build_target, ["tests"])

    def test_kitchen_sink_auto_fix_dynamic_import_updates_inline_block_and_succeeds(self):
        with fixture_project("kitchen_sink") as project_root:
            entrypoint = project_root / "functions" / "reports_refresh.py"

            def fake_pip_install(build_target: Path, requirements_path: Path, **_kwargs) -> None:
                requirements_text = requirements_path.read_text(encoding="utf-8")
                self.assertIn("idna==3.10\n", requirements_text)
                (build_target / "idna.py").write_text("__version__ = '3.10'\n", encoding="utf-8")

            with mock.patch("monopack.build._pip_install_target", side_effect=fake_pip_install):
                build_target = build_function(
                    function_name="reports_refresh",
                    functions_dir=project_root / "functions",
                    build_dir=project_root / "build",
                    project_root=project_root,
                    verify=True,
                    mode="deploy",
                    auto_fix=True,
                )

            rewritten = entrypoint.read_text(encoding="utf-8")
            parsed = parse_inline_config(rewritten)

            assert_files_exist(self, build_target, ["app/reports/generator.py"])
            self.assertIn("# monopack-start\n", rewritten)
            self.assertIn("idna", {name.lower() for name in parsed.extra_distributions})

    def test_build_function_no_auto_fix_preserves_failure_and_entrypoint(self):
        with fixture_project("auto_fix_first_party") as project_root:
            entrypoint = project_root / "functions" / "users_get.py"
            original_source = entrypoint.read_text(encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "Build verification failed"):
                build_function(
                    function_name="users_get",
                    functions_dir=project_root / "functions",
                    build_dir=project_root / "build",
                    project_root=project_root,
                    verify=True,
                    auto_fix=False,
                )

            self.assertEqual(entrypoint.read_text(encoding="utf-8"), original_source)

    def test_cli_auto_fix_off_by_default_keeps_failure_and_does_not_modify_entrypoint(self):
        with fixture_project("auto_fix_first_party") as project_root:
            entrypoint = project_root / "functions" / "users_get.py"
            original_source = entrypoint.read_text(encoding="utf-8")

            result, stdout, stderr = run_cli_captured(
                cli_main,
                [
                    "users_get",
                    "--functions-dir",
                    str(project_root / "functions"),
                    "--build-dir",
                    str(project_root / "build"),
                    "--verify",
                ],
            )

            self.assertEqual(result, 2)
            self.assertEqual(stdout, "")
            self.assertIn("Build verification failed", stderr)
            self.assertEqual(entrypoint.read_text(encoding="utf-8"), original_source)


if __name__ == "__main__":
    unittest.main()
