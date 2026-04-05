"""Package-manager detection helpers for dependency cache preparation."""

from pathlib import Path


SUPPORTED_PACKAGE_MANAGERS = ("auto", "pip", "uv", "poetry", "pipenv")


def _pyproject_declares_poetry(pyproject_path: Path) -> bool:
    if not pyproject_path.exists() or not pyproject_path.is_file():
        return False

    content = pyproject_path.read_text(encoding="utf-8")
    return "[tool.poetry]" in content


def detect_package_manager_candidates(project_root: Path) -> set[str]:
    """Return package-manager candidates inferred from project files."""

    candidates: set[str] = set()

    if (project_root / "uv.lock").is_file():
        candidates.add("uv")

    if (project_root / "poetry.lock").is_file() or _pyproject_declares_poetry(
        project_root / "pyproject.toml"
    ):
        candidates.add("poetry")

    if (project_root / "Pipfile.lock").is_file() or (project_root / "Pipfile").is_file():
        candidates.add("pipenv")

    if (project_root / "requirements.txt").is_file():
        candidates.add("pip")

    return candidates


def resolve_package_manager(project_root: Path, requested: str) -> str:
    """Resolve package manager from explicit request or local file signals."""

    normalized = requested.strip().lower()
    if normalized not in SUPPORTED_PACKAGE_MANAGERS:
        supported = ", ".join(SUPPORTED_PACKAGE_MANAGERS)
        raise ValueError(
            f"Unsupported package manager '{requested}'. Supported values: {supported}."
        )

    if normalized != "auto":
        return normalized

    candidates = sorted(detect_package_manager_candidates(project_root))
    if len(candidates) == 1:
        return candidates[0]

    if not candidates:
        raise ValueError(
            "Could not auto-detect a package manager from project files. "
            "Add one of: requirements.txt, uv.lock, poetry.lock/pyproject.toml "
            "with [tool.poetry], or Pipfile/Pipfile.lock, or pass --package-manager."
        )

    raise ValueError(
        "Could not auto-detect a unique package manager; multiple candidates found: "
        f"{', '.join(candidates)}. Pass --package-manager to choose one."
    )
