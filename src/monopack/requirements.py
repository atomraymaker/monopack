import re
from pathlib import Path


_PINNED_REQUIREMENT_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)\s*==\s*(?P<version>[^\s#]+)$"
)


def _normalize_distribution_name(name: str) -> str:
    return name.lower().replace("_", "-")


def parse_pinned_requirements(path: Path) -> dict[str, str]:
    parsed: dict[str, str] = {}

    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        match = _PINNED_REQUIREMENT_RE.fullmatch(line)
        if not match:
            raise ValueError(
                f"Unsupported requirement format on line {line_number}: {line!r}. "
                "Only pinned 'name==version' entries are allowed."
            )

        original_name = match.group("name")
        version = match.group("version")
        normalized_name = _normalize_distribution_name(original_name)
        parsed[normalized_name] = f"{original_name}=={version}"

    return parsed


def filter_requirements_for_distributions(
    parsed: dict[str, str], needed_distributions: set[str]
) -> list[str]:
    normalized_needed = {
        _normalize_distribution_name(distribution)
        for distribution in needed_distributions
    }

    missing = sorted(distribution for distribution in normalized_needed if distribution not in parsed)
    if missing:
        missing_display = ", ".join(missing)
        raise KeyError(
            f"Missing pinned requirements for distributions: {missing_display}"
        )

    return sorted(parsed[distribution] for distribution in normalized_needed)
