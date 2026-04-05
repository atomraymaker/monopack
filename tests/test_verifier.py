from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from monopack.verifier import run_unittest_discovery, verifier_script_source


class VerifierTests(unittest.TestCase):
    def test_verifier_script_source_imports_selected_modules_then_handler(self):
        script = verifier_script_source(
            pack_name="users_get",
            selected_modules={"app.users.service", "packs.users_get", "app.shared.auth"},
        )

        self.assertEqual(
            script,
            "import app.shared.auth\n"
            "import app.users.service\n"
            "import packs.users_get\n"
            "import packs.users_get as target\n"
            "assert hasattr(target, 'lambda_handler'), 'lambda_handler is missing'\n",
        )

    def test_run_unittest_discovery_invokes_unittest_discover_from_build_target(self):
        with mock.patch(
            "monopack.verifier.subprocess.run",
            return_value=subprocess.CompletedProcess(args=["python"], returncode=0, stdout="", stderr=""),
        ) as run:
            run_unittest_discovery(Path("/tmp/build/tests"), cwd=Path("/tmp/build"))

        run.assert_called_once_with(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
            cwd=Path("/tmp/build"),
            capture_output=True,
            text=True,
        )

    def test_run_unittest_discovery_raises_runtimeerror_with_output(self):
        completed = subprocess.CompletedProcess(
            args=["python", "-m", "unittest"],
            returncode=1,
            stdout="test output",
            stderr="traceback",
        )

        with mock.patch("monopack.verifier.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(
                RuntimeError,
                r"Test discovery failed\..*stdout:\n"
                r"test output\n"
                r"stderr:\n"
                r"traceback",
            ):
                run_unittest_discovery(Path("/tmp/build/tests"), cwd=Path("/tmp/build"))


if __name__ == "__main__":
    unittest.main()
