from pathlib import Path


def module_name_from_path(path: Path, project_root: Path) -> str:
    relative = path.relative_to(project_root)
    if relative.name == "__init__.py":
        parts = relative.parent.parts
    else:
        parts = relative.with_suffix("").parts
    return ".".join(parts)


def resolve_module_to_file(module: str, project_root: Path) -> Path | None:
    module_path = Path(*module.split("."))

    module_file = project_root / module_path.with_suffix(".py")
    if module_file.exists():
        return module_file

    package_init = project_root / module_path / "__init__.py"
    if package_init.exists():
        return package_init

    return None


def parent_init_files(path: Path, project_root: Path) -> list[Path]:
    relative_parent = path.relative_to(project_root).parent

    init_files: list[Path] = []
    for index in range(1, len(relative_parent.parts) + 1):
        parent_dir = project_root.joinpath(*relative_parent.parts[:index])
        init_file = parent_dir / "__init__.py"
        if init_file.exists():
            init_files.append(init_file)

    return init_files
