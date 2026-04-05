from pathlib import Path


def discover_packs(packs_dir: Path) -> list[str]:
    return sorted(
        path.stem
        for path in packs_dir.glob("*.py")
        if path.is_file() and not path.name.startswith("_")
    )


def resolve_pack_entrypoint(packs_dir: Path, pack_name: str) -> Path:
    entrypoint = packs_dir / f"{pack_name}.py"
    if entrypoint.is_file():
        return entrypoint

    raise FileNotFoundError(
        f"Pack '{pack_name}' not found in {packs_dir}"
    )
