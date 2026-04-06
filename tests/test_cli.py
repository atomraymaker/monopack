import io
import runpy
import shutil
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import unittest
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from monopack import cli


class CliTests(unittest.TestCase):
    def test_module_entrypoint_invokes_main(self):
        with mock.patch("monopack.cli.main", return_value=0) as main:
            with self.assertRaises(SystemExit) as exc:
                runpy.run_module("monopack.__main__", run_name="__main__")

        self.assertEqual(exc.exception.code, 0)
        main.assert_called_once_with()

    def test_parse_args_defaults(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            args = cli.parse_args([])

        self.assertIsNone(args.pack_name)
        self.assertEqual(args.packs_dir, "packs")
        self.assertEqual(args.build_dir, "build")
        self.assertTrue(args.verify)
        self.assertFalse(args.auto_fix)
        self.assertEqual(args.mode, "deploy")
        self.assertFalse(args.with_tests)
        self.assertFalse(args.debug)
        self.assertEqual(args.jobs, "auto")
        self.assertEqual(args.sha_output, "hex")
        self.assertEqual(args.package_manager, "auto")
        self.assertIsNone(args.existing_install_python)

    def test_parse_args_custom_values(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            args = cli.parse_args(
                [
                    "my_func",
                    "--packs-dir",
                    "fns",
                    "--build-dir",
                    "out",
                    "--no-verify",
                    "--mode",
                    "test",
                    "--with-tests",
                    "--auto-fix",
                    "--debug",
                    "--jobs",
                    "3",
                    "--sha-output",
                    "hex,b64",
                    "--package-manager",
                    "poetry",
                    "--existing-install-python",
                    ".venv/bin/python",
                ]
            )

        self.assertEqual(args.pack_name, "my_func")
        self.assertEqual(args.packs_dir, "fns")
        self.assertEqual(args.build_dir, "out")
        self.assertFalse(args.verify)
        self.assertTrue(args.auto_fix)
        self.assertEqual(args.mode, "test")
        self.assertTrue(args.with_tests)
        self.assertTrue(args.debug)
        self.assertEqual(args.jobs, "3")
        self.assertEqual(args.sha_output, "hex,b64")
        self.assertEqual(args.package_manager, "poetry")
        self.assertEqual(args.existing_install_python, ".venv/bin/python")

    def test_parse_args_version_flag(self):
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as exc:
                cli.parse_args(["--version"])

        self.assertEqual(exc.exception.code, 0)
        self.assertEqual(stdout.getvalue().strip(), f"monopack {cli.__version__}")
        self.assertEqual(stderr.getvalue(), "")

    def test_parse_sha_output_accepts_comma_separated_values(self):
        self.assertEqual(cli._parse_sha_output("hex,b64"), {"hex", "b64"})
        self.assertEqual(cli._parse_sha_output(" b64 "), {"b64"})

    def test_parse_jobs_accepts_auto_and_positive_integer(self):
        self.assertEqual(cli._parse_jobs("auto"), "auto")
        self.assertEqual(cli._parse_jobs("4"), 4)

    def test_parse_jobs_rejects_invalid_values(self):
        with self.assertRaisesRegex(ValueError, "Invalid --jobs value"):
            cli._parse_jobs("0")
        with self.assertRaisesRegex(ValueError, "Invalid --jobs value"):
            cli._parse_jobs("many")

    def test_parse_sha_output_rejects_invalid_values(self):
        with self.assertRaisesRegex(ValueError, "Unsupported --sha-output values"):
            cli._parse_sha_output("hex,md5")

        with self.assertRaisesRegex(ValueError, "Invalid --sha-output value"):
            cli._parse_sha_output(" , ")

    def test_parse_args_uses_env_defaults_when_flags_absent(self):
        with mock.patch.dict(
            "os.environ",
            {
                "MONOPACK_PACKS_DIR": "env_packs",
                "MONOPACK_BUILD_DIR": "env_build",
                "MONOPACK_MODE": "test",
                "MONOPACK_VERIFY": "no",
                "MONOPACK_AUTO_FIX": "0",
                "MONOPACK_WITH_TESTS": "yes",
                "MONOPACK_DEBUG": "true",
                "MONOPACK_JOBS": "5",
            },
            clear=True,
        ):
            args = cli.parse_args([])

        self.assertEqual(args.packs_dir, "env_packs")
        self.assertEqual(args.build_dir, "env_build")
        self.assertEqual(args.mode, "test")
        self.assertFalse(args.verify)
        self.assertFalse(args.auto_fix)
        self.assertTrue(args.with_tests)
        self.assertTrue(args.debug)
        self.assertEqual(args.jobs, "5")
        self.assertIsNone(args.existing_install_python)

    def test_parse_args_uses_existing_install_python_env_default(self):
        with mock.patch.dict(
            "os.environ",
            {
                "MONOPACK_EXISTING_INSTALL_PYTHON": "/tmp/custom-python",
            },
            clear=True,
        ):
            args = cli.parse_args([])

        self.assertEqual(args.existing_install_python, "/tmp/custom-python")

    def test_parse_args_cli_flags_override_env_values(self):
        with mock.patch.dict(
            "os.environ",
            {
                "MONOPACK_PACKS_DIR": "env_packs",
                "MONOPACK_BUILD_DIR": "env_build",
                "MONOPACK_MODE": "test",
                "MONOPACK_VERIFY": "false",
                "MONOPACK_AUTO_FIX": "false",
                "MONOPACK_WITH_TESTS": "true",
                "MONOPACK_JOBS": "5",
            },
            clear=True,
        ):
            args = cli.parse_args(
                [
                    "--packs-dir",
                    "arg_packs",
                    "--build-dir",
                    "arg_build",
                    "--mode",
                    "deploy",
                    "--verify",
                    "--auto-fix",
                    "--jobs",
                    "2",
                ]
            )

        self.assertEqual(args.packs_dir, "arg_packs")
        self.assertEqual(args.build_dir, "arg_build")
        self.assertEqual(args.mode, "deploy")
        self.assertTrue(args.verify)
        self.assertTrue(args.auto_fix)
        self.assertTrue(args.with_tests)
        self.assertEqual(args.jobs, "2")

    def test_main_returns_error_for_invalid_env_bool(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            packs_dir = project_root / "packs"
            packs_dir.mkdir(parents=True)
            (packs_dir / "users_get.py").write_text("", encoding="utf-8")
            (project_root / "requirements.txt").write_text("", encoding="utf-8")

            stdout = io.StringIO()
            stderr = io.StringIO()
            with mock.patch.dict(
                "os.environ",
                {
                    "MONOPACK_PACKS_DIR": str(packs_dir),
                    "MONOPACK_BUILD_DIR": str(project_root / "build"),
                    "MONOPACK_VERIFY": "maybe",
                },
                clear=True,
            ):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    result = cli.main([])

        self.assertEqual(result, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Invalid boolean value for MONOPACK_VERIFY", stderr.getvalue())

    def test_main_returns_error_for_invalid_env_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            packs_dir = project_root / "packs"
            packs_dir.mkdir(parents=True)
            (packs_dir / "users_get.py").write_text("", encoding="utf-8")
            (project_root / "requirements.txt").write_text("", encoding="utf-8")

            stdout = io.StringIO()
            stderr = io.StringIO()
            with mock.patch.dict(
                "os.environ",
                {
                    "MONOPACK_PACKS_DIR": str(packs_dir),
                    "MONOPACK_BUILD_DIR": str(project_root / "build"),
                    "MONOPACK_MODE": "staging",
                },
                clear=True,
            ):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    result = cli.main(["users_get"])

        self.assertEqual(result, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Invalid mode 'staging'", stderr.getvalue())

    def test_main_uses_env_mode_for_test_behavior(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            fixture_root = Path(__file__).resolve().parent / "fixtures" / "simple"
            shutil.copytree(fixture_root, project_root)
            packs_dir = project_root / "packs"
            build_dir = project_root / "build"
            app_users_dir = project_root / "app" / "users"
            app_users_dir.mkdir(parents=True)
            (project_root / "app" / "__init__.py").write_text("", encoding="utf-8")
            (app_users_dir / "__init__.py").write_text("", encoding="utf-8")
            (app_users_dir / "service.py").write_text(
                "def get_profile():\n    return {'id': 1}\n",
                encoding="utf-8",
            )
            (packs_dir / "users_get.py").write_text(
                "from app.users.service import get_profile\n"
                "\n"
                "\n"
                "def lambda_handler(event, context):\n"
                "    return {'statusCode': 200, 'body': get_profile()}\n",
                encoding="utf-8",
            )
            tests_dir = project_root / "tests" / "users"
            tests_dir.mkdir(parents=True)
            (project_root / "tests" / "__init__.py").write_text("", encoding="utf-8")
            (tests_dir / "__init__.py").write_text("", encoding="utf-8")
            (tests_dir / "test_users_get.py").write_text(
                "import unittest\n"
                "from app.users import service\n"
                "\n"
                "\n"
                "class UsersGetTests(unittest.TestCase):\n"
                "    def test_smoke(self):\n"
                "        self.assertEqual(service.get_profile()['id'], 1)\n",
                encoding="utf-8",
            )

            stdout = io.StringIO()
            stderr = io.StringIO()
            with mock.patch.dict(
                "os.environ",
                {
                    "MONOPACK_PACKS_DIR": str(packs_dir),
                    "MONOPACK_BUILD_DIR": str(build_dir),
                    "MONOPACK_MODE": "test",
                },
                clear=True,
            ):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    result = cli.main(["users_get"])

            tests_copied = (
                build_dir / "users_get" / "tests" / "users" / "test_users_get.py"
            ).is_file()

        self.assertEqual(result, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertTrue(tests_copied)

    def test_main_returns_error_when_with_tests_used_in_test_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            packs_dir = project_root / "packs"
            packs_dir.mkdir(parents=True)
            (project_root / "requirements.txt").write_text("", encoding="utf-8")

            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = cli.main(
                    [
                        "--packs-dir",
                        str(packs_dir),
                        "--with-tests",
                        "--mode",
                        "test",
                    ]
                )

        self.assertEqual(result, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn(
            "--with-tests is only valid with --mode deploy",
            stderr.getvalue(),
        )

    def test_main_builds_all_packs_when_no_target(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            fixture_root = Path(__file__).resolve().parent / "fixtures" / "simple"
            shutil.copytree(fixture_root, project_root)
            packs_dir = project_root / "packs"
            build_dir = project_root / "build"

            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = cli.main(
                    [
                        "--packs-dir",
                        str(packs_dir),
                        "--build-dir",
                        str(build_dir),
                    ]
                )

        self.assertEqual(result, 0)
        self.assertIn(str(build_dir / "users_get"), stdout.getvalue())
        self.assertEqual(stderr.getvalue(), "")

    def test_main_prints_build_target_for_target(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            fixture_root = Path(__file__).resolve().parent / "fixtures" / "simple"
            shutil.copytree(fixture_root, project_root)
            packs_dir = project_root / "packs"
            build_dir = project_root / "build"

            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = cli.main(
                    [
                        "users_get",
                        "--packs-dir",
                        str(packs_dir),
                        "--build-dir",
                        str(build_dir),
                    ]
                )

        self.assertEqual(result, 0)
        self.assertEqual(stdout.getvalue(), f"{build_dir / 'users_get'}\n")
        self.assertEqual(stderr.getvalue(), "")

    def test_main_returns_error_when_target_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            packs_dir = project_root / "packs"
            packs_dir.mkdir(parents=True)
            (project_root / "requirements.txt").write_text("", encoding="utf-8")

            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = cli.main(["missing", "--packs-dir", str(packs_dir)])

        self.assertEqual(result, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Pack 'missing' not found", stderr.getvalue())

    def test_main_returns_error_when_no_functions_discovered(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            packs_dir = project_root / "packs"
            packs_dir.mkdir(parents=True)
            (project_root / "requirements.txt").write_text("", encoding="utf-8")

            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = cli.main(["--packs-dir", str(packs_dir)])

        self.assertEqual(result, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("No packs discovered", stderr.getvalue())

    def test_main_returns_error_when_packs_dir_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_packs_dir = Path(tmpdir) / "missing"

            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = cli.main(["--packs-dir", str(missing_packs_dir)])

        self.assertEqual(result, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Packs directory does not exist", stderr.getvalue())

    def test_main_returns_error_when_packs_dir_is_not_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            project_root.mkdir(parents=True)
            functions_file = project_root / "packs"
            functions_file.write_text("", encoding="utf-8")

            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = cli.main(["--packs-dir", str(functions_file)])

        self.assertEqual(result, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Packs directory is not a directory", stderr.getvalue())

    def test_main_returns_error_when_build_dir_equals_packs_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            packs_dir = project_root / "packs"
            packs_dir.mkdir(parents=True)
            (project_root / "requirements.txt").write_text("", encoding="utf-8")

            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = cli.main(
                    [
                        "--packs-dir",
                        str(packs_dir),
                        "--build-dir",
                        str(packs_dir),
                    ]
                )

        self.assertEqual(result, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn(
            "Build directory must be different from packs directory",
            stderr.getvalue(),
        )

    def test_main_returns_error_when_build_dir_inside_packs_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            packs_dir = project_root / "packs"
            packs_dir.mkdir(parents=True)
            (project_root / "requirements.txt").write_text("", encoding="utf-8")
            nested_build_dir = packs_dir / "build"

            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = cli.main(
                    [
                        "--packs-dir",
                        str(packs_dir),
                        "--build-dir",
                        str(nested_build_dir),
                    ]
                )

        self.assertEqual(result, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn(
            "Build directory must not be inside packs directory",
            stderr.getvalue(),
        )

    def test_main_returns_error_when_dependency_source_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            packs_dir = project_root / "packs"
            packs_dir.mkdir(parents=True)

            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = cli.main(["--packs-dir", str(packs_dir)])

        self.assertEqual(result, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Could not auto-detect a package manager", stderr.getvalue())

    def test_main_threads_package_manager_to_build_pack(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            packs_dir = project_root / "packs"
            build_dir = project_root / "build"
            packs_dir.mkdir(parents=True)
            (packs_dir / "users_get.py").write_text("", encoding="utf-8")
            (project_root / "uv.lock").write_text("", encoding="utf-8")

            with mock.patch(
                "monopack.cli.build_pack", return_value=build_dir / "users_get"
            ) as build:
                result = cli.main(
                    [
                        "users_get",
                        "--packs-dir",
                        str(packs_dir),
                        "--build-dir",
                        str(build_dir),
                        "--package-manager",
                        "uv",
                    ]
                )

        self.assertEqual(result, 0)
        self.assertEqual(build.call_args.kwargs["package_manager"], "uv")

    def test_main_threads_existing_install_python_to_build_pack(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            packs_dir = project_root / "packs"
            build_dir = project_root / "build"
            packs_dir.mkdir(parents=True)
            (packs_dir / "users_get.py").write_text("", encoding="utf-8")
            (project_root / "requirements.txt").write_text("", encoding="utf-8")

            with mock.patch(
                "monopack.cli.build_pack", return_value=build_dir / "users_get"
            ) as build:
                result = cli.main(
                    [
                        "users_get",
                        "--packs-dir",
                        str(packs_dir),
                        "--build-dir",
                        str(build_dir),
                        "--existing-install-python",
                        ".venv/bin/python",
                    ]
                )

        self.assertEqual(result, 0)
        self.assertEqual(
            build.call_args.kwargs["existing_install_python"],
            ".venv/bin/python",
        )

    def test_main_returns_error_for_invalid_discovered_pack_name(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            packs_dir = project_root / "packs"
            packs_dir.mkdir(parents=True)
            (project_root / "requirements.txt").write_text("", encoding="utf-8")
            (packs_dir / "bad-name.py").write_text("", encoding="utf-8")

            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = cli.main(["--packs-dir", str(packs_dir)])

        self.assertEqual(result, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Invalid pack name 'bad-name'", stderr.getvalue())

    def test_main_returns_error_for_invalid_target_pack_name(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            packs_dir = project_root / "packs"
            packs_dir.mkdir(parents=True)
            (project_root / "requirements.txt").write_text("", encoding="utf-8")

            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = cli.main(["nested/users", "--packs-dir", str(packs_dir)])

        self.assertEqual(result, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn(
            "Target pack name must not contain path separators or dots",
            stderr.getvalue(),
        )

    def test_main_returns_error_when_test_mode_has_no_tests_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            packs_dir = project_root / "packs"
            packs_dir.mkdir(parents=True)
            (project_root / "requirements.txt").write_text("", encoding="utf-8")

            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = cli.main(["--packs-dir", str(packs_dir), "--mode", "test"])

        self.assertEqual(result, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("requires a project tests directory", stderr.getvalue())

    def test_main_returns_error_for_invalid_sha_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            packs_dir = project_root / "packs"
            packs_dir.mkdir(parents=True)
            (packs_dir / "users_get.py").write_text("", encoding="utf-8")
            (project_root / "requirements.txt").write_text("", encoding="utf-8")

            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = cli.main(
                    [
                        "users_get",
                        "--packs-dir",
                        str(packs_dir),
                        "--sha-output",
                        "hex,md5",
                    ]
                )

        self.assertEqual(result, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Unsupported --sha-output values", stderr.getvalue())

    def test_main_threads_auto_fix_to_build_pack(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            fixture_root = Path(__file__).resolve().parent / "fixtures" / "simple"
            shutil.copytree(fixture_root, project_root)
            packs_dir = project_root / "packs"
            build_dir = project_root / "build"

            with mock.patch(
                "monopack.cli.build_pack", return_value=build_dir / "users_get"
            ) as build:
                result = cli.main(
                    [
                        "users_get",
                        "--packs-dir",
                        str(packs_dir),
                        "--build-dir",
                        str(build_dir),
                        "--auto-fix",
                    ]
                )

        self.assertEqual(result, 0)
        self.assertTrue(build.call_args.kwargs["auto_fix"])
        self.assertFalse(build.call_args.kwargs["with_tests"])
        self.assertEqual(build.call_args.kwargs["sha_outputs"], {"hex"})

    def test_main_threads_with_tests_to_build_pack(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            fixture_root = Path(__file__).resolve().parent / "fixtures" / "test_mode"
            shutil.copytree(fixture_root, project_root)
            packs_dir = project_root / "packs"
            build_dir = project_root / "build"

            with mock.patch(
                "monopack.cli.build_pack", return_value=build_dir / "users_get"
            ) as build:
                result = cli.main(
                    [
                        "users_get",
                        "--packs-dir",
                        str(packs_dir),
                        "--build-dir",
                        str(build_dir),
                        "--mode",
                        "deploy",
                        "--with-tests",
                    ]
                )

        self.assertEqual(result, 0)
        self.assertTrue(build.call_args.kwargs["with_tests"])

    def test_main_threads_sha_outputs_to_build_pack(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            fixture_root = Path(__file__).resolve().parent / "fixtures" / "simple"
            shutil.copytree(fixture_root, project_root)
            packs_dir = project_root / "packs"
            build_dir = project_root / "build"

            with mock.patch(
                "monopack.cli.build_pack", return_value=build_dir / "users_get"
            ) as build:
                result = cli.main(
                    [
                        "users_get",
                        "--packs-dir",
                        str(packs_dir),
                        "--build-dir",
                        str(build_dir),
                        "--sha-output",
                        "hex,b64",
                    ]
                )

        self.assertEqual(result, 0)
        self.assertEqual(build.call_args.kwargs["sha_outputs"], {"hex", "b64"})

    def test_main_threads_debug_to_build_pack(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            fixture_root = Path(__file__).resolve().parent / "fixtures" / "simple"
            shutil.copytree(fixture_root, project_root)
            packs_dir = project_root / "packs"
            build_dir = project_root / "build"

            with mock.patch(
                "monopack.cli.build_pack", return_value=build_dir / "users_get"
            ) as build:
                result = cli.main(
                    [
                        "users_get",
                        "--packs-dir",
                        str(packs_dir),
                        "--build-dir",
                        str(build_dir),
                        "--debug",
                    ]
                )

        self.assertEqual(result, 0)
        self.assertTrue(build.call_args.kwargs["debug"])

    def test_main_builds_all_packs_with_jobs_and_deterministic_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            packs_dir = project_root / "packs"
            build_dir = project_root / "build"
            packs_dir.mkdir(parents=True)
            (packs_dir / "users_get.py").write_text("", encoding="utf-8")
            (packs_dir / "billing_charge.py").write_text("", encoding="utf-8")
            (project_root / "requirements.txt").write_text("", encoding="utf-8")

            sentinel_shared_state = object()

            def _fake_build(pack_name, **kwargs):
                self.assertIs(kwargs["shared_state"], sentinel_shared_state)
                return build_dir / pack_name

            stdout = io.StringIO()
            stderr = io.StringIO()
            with mock.patch(
                "monopack.cli.prewarm_shared_build_state",
                return_value=sentinel_shared_state,
            ) as prewarm:
                with mock.patch(
                    "monopack.cli.build_pack", side_effect=_fake_build
                ) as build:
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        result = cli.main(
                            [
                                "--packs-dir",
                                str(packs_dir),
                                "--build-dir",
                                str(build_dir),
                                "--jobs",
                                "2",
                            ]
                        )

        self.assertEqual(result, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(
            stdout.getvalue().splitlines(),
            [
                str(build_dir / "billing_charge"),
                str(build_dir / "users_get"),
            ],
        )
        prewarm.assert_called_once()
        self.assertEqual(build.call_count, 2)

    def test_resolve_jobs_uses_auto_default_based_on_pack_count(self):
        with mock.patch("os.cpu_count", return_value=12):
            jobs = cli._resolve_jobs(
                "auto",
                pack_count=10,
                auto_fix=False,
                has_target=False,
            )

        self.assertEqual(jobs, 8)

    def test_resolve_jobs_forces_serial_with_auto_fix(self):
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            jobs = cli._resolve_jobs(
                "6",
                pack_count=6,
                auto_fix=True,
                has_target=False,
            )

        self.assertEqual(jobs, 1)
        self.assertIn("forcing --jobs=1", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
