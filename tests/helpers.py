import io
import shutil
import tempfile
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


@contextmanager
def fixture_project(fixture_name):
    fixture_root = FIXTURES_DIR / fixture_name
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir) / "project"
        shutil.copytree(fixture_root, project_root)
        yield project_root


def run_cli_captured(cli_main, argv):
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = cli_main(argv)
    return code, stdout.getvalue(), stderr.getvalue()


def assert_files_exist(testcase, root, relative_paths):
    for relative_path in relative_paths:
        testcase.assertTrue((root / relative_path).is_file(), relative_path)


def assert_paths_not_exist(testcase, root, relative_paths):
    for relative_path in relative_paths:
        testcase.assertFalse((root / relative_path).exists(), relative_path)
