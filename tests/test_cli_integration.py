import sys
from pathlib import Path
import unittest
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from monopack import build as build_module
from monopack import cli
from helpers import assert_files_exist, assert_paths_not_exist, fixture_project, run_cli_captured


class CliIntegrationTests(unittest.TestCase):
    def test_debug_mode_prints_aggregated_resolution_report(self):
        with fixture_project("simple") as project_root:
            code, stdout, stderr = run_cli_captured(
                cli.main,
                [
                    "users_get",
                    "--functions-dir",
                    str(project_root / "functions"),
                    "--build-dir",
                    str(project_root / "build"),
                    "--no-verify",
                    "--debug",
                ],
            )

            self.assertEqual(code, 0)
            self.assertIn(str(project_root / "build" / "users_get"), stdout)
            self.assertIn("[debug] Build report for 'users_get'", stderr)
            self.assertIn("import_roots=", stderr)

    def test_kitchen_sink_users_test_mode_verify_runs_verifier_and_unittest(self):
        with fixture_project("kitchen_sink") as project_root:
            build_dir = project_root / "build"

            verifier_calls = []
            unittest_calls = []
            real_run_verifier = build_module.run_verifier_script
            real_run_unittest = build_module.run_unittest_discovery

            def fake_pip_install(build_target: Path, requirements_path: Path, **_kwargs) -> None:
                requirements = requirements_path.read_text(encoding="utf-8")
                self.assertEqual(requirements, "colorama==0.4.6\nrequests==2.32.3\n")
                (build_target / "colorama.py").write_text(
                    "__version__ = '0.4.6'\n",
                    encoding="utf-8",
                )
                (build_target / "requests.py").write_text(
                    "__version__ = '2.32.3'\n",
                    encoding="utf-8",
                )

            def tracked_run_verifier(script_path: Path, cwd: Path) -> None:
                verifier_calls.append((script_path, cwd))
                real_run_verifier(script_path, cwd)

            def tracked_run_unittest(tests_dir: Path, cwd: Path) -> None:
                unittest_calls.append((tests_dir, cwd))
                real_run_unittest(tests_dir, cwd)

            with mock.patch(
                "monopack.build._pip_install_target",
                side_effect=fake_pip_install,
            ):
                with mock.patch(
                    "monopack.build.run_verifier_script",
                    side_effect=tracked_run_verifier,
                ):
                    with mock.patch(
                        "monopack.build.run_unittest_discovery",
                        side_effect=tracked_run_unittest,
                    ):
                        code, _, stderr = run_cli_captured(
                            cli.main,
                            [
                                "users_get",
                                "--functions-dir",
                                str(project_root / "functions"),
                                "--build-dir",
                                str(build_dir),
                                "--mode",
                                "test",
                                "--verify",
                            ]
                        )

            build_target = build_dir / "users_get"
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            self.assertEqual(len(verifier_calls), 1)
            self.assertEqual(len(unittest_calls), 1)
            self.assertEqual(verifier_calls[0][0], build_target / "_monopack_verify.py")
            self.assertEqual(verifier_calls[0][1], build_target)
            self.assertEqual(unittest_calls[0][0], build_target / "tests")
            self.assertEqual(unittest_calls[0][1], build_target)
            self.assertTrue((build_target / "tests" / "users" / "test_users_get.py").is_file())
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

    def test_kitchen_sink_billing_deploy_mode_verify_excludes_tests(self):
        with fixture_project("kitchen_sink") as project_root:
            build_dir = project_root / "build"

            with mock.patch("monopack.build._pip_install_target") as pip_install:
                code, _, stderr = run_cli_captured(
                    cli.main,
                    [
                        "billing_charge",
                        "--functions-dir",
                        str(project_root / "functions"),
                        "--build-dir",
                        str(build_dir),
                        "--mode",
                        "deploy",
                        "--verify",
                    ]
                )

            build_target = build_dir / "billing_charge"
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            self.assertFalse((build_target / "tests").exists())
            self.assertFalse((build_target / "requirements.txt").exists())
            pip_install.assert_not_called()

    def test_auto_fix_first_party_runs_through_cli_and_rewrites_entrypoint(self):
        with fixture_project("auto_fix_first_party") as project_root:
            build_dir = project_root / "build"
            entrypoint = project_root / "functions" / "users_get.py"

            code, _, stderr = run_cli_captured(
                cli.main,
                [
                    "users_get",
                    "--functions-dir",
                    str(project_root / "functions"),
                    "--build-dir",
                    str(build_dir),
                    "--verify",
                    "--auto-fix",
                ]
            )

            rewritten = entrypoint.read_text(encoding="utf-8")
            build_target = build_dir / "users_get"

            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            self.assertTrue((build_target / "app" / "hidden" / "runtime_dep.py").is_file())
            self.assertIn("# monopack-start\n", rewritten)
            self.assertIn("# extra_modules: app.hidden.runtime_dep\n", rewritten)

    def test_literal_dynamic_imports_resolve_without_auto_fix_through_cli(self):
        with fixture_project("dynamic_literal_imports") as project_root:
            build_dir = project_root / "build"
            entrypoint = project_root / "functions" / "users_get.py"
            original_source = entrypoint.read_text(encoding="utf-8")

            def fake_pip_install(build_target: Path, requirements_path: Path, **_kwargs) -> None:
                self.assertEqual(
                    requirements_path.read_text(encoding="utf-8"),
                    "idna==3.10\n",
                )
                (build_target / "idna.py").write_text("__version__ = '3.10'\n", encoding="utf-8")

            with mock.patch("monopack.build._pip_install_target", side_effect=fake_pip_install) as pip_install:
                code, _, stderr = run_cli_captured(
                    cli.main,
                    [
                        "users_get",
                        "--functions-dir",
                        str(project_root / "functions"),
                        "--build-dir",
                        str(build_dir),
                        "--verify",
                    ],
                )

            build_target = build_dir / "users_get"
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
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

    def test_with_tests_test_mode_returns_validation_error(self):
        with fixture_project("simple") as project_root:
            code, stdout, stderr = run_cli_captured(
                cli.main,
                [
                    "users_get",
                    "--functions-dir",
                    str(project_root / "functions"),
                    "--build-dir",
                    str(project_root / "build"),
                    "--mode",
                    "test",
                    "--with-tests",
                ],
            )

            self.assertEqual(code, 2)
            self.assertEqual(stdout, "")
            self.assertIn(
                "--with-tests is only valid with --mode deploy",
                stderr,
            )

    def test_test_mode_skips_zip_creation(self):
        with fixture_project("test_mode") as project_root:
            build_dir = project_root / "build"
            with mock.patch("monopack.build._pip_install_target"):
                code, _, stderr = run_cli_captured(
                    cli.main,
                    [
                        "users_get",
                        "--functions-dir",
                        str(project_root / "functions"),
                        "--build-dir",
                        str(build_dir),
                        "--mode",
                        "test",
                        "--no-verify",
                    ],
                )

            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            self.assertFalse((build_dir / "users_get.zip").exists())

    def test_build_all_functions_writes_requested_sha_outputs(self):
        with fixture_project("kitchen_sink") as project_root:
            build_dir = project_root / "build"

            with mock.patch("monopack.build._pip_install_target"):
                code, _, stderr = run_cli_captured(
                    cli.main,
                    [
                        "--functions-dir",
                        str(project_root / "functions"),
                        "--build-dir",
                        str(build_dir),
                        "--mode",
                        "deploy",
                        "--no-verify",
                        "--sha-output",
                        "hex,b64",
                    ],
                )

            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            for function_name in ("billing_charge", "users_get"):
                self.assertTrue((build_dir / f"{function_name}.package.sha256").is_file())
                self.assertTrue((build_dir / f"{function_name}.package.sha256.b64").is_file())


if __name__ == "__main__":
    unittest.main()
