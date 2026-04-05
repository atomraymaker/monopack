# Changelog

## 0.3.1

- Added `--package-manager` with `auto|pip|uv|poetry|pipenv` to support non-pip lock/export flows.
- Added project-file auto-detection for package manager selection and explicit override support.
- Added package-manager export command mapping to normalize dependency sources into the existing build cache pipeline.
- Updated validation and tests for auto-detection ambiguity/missing-source errors and package-manager threading through builds.

## 0.3.0

- Breaking rename: switched entrypoint terminology and structure from `functions` to `packs` across CLI flags, env vars, runtime module imports, docs, and fixtures.
- Renamed core APIs to pack-oriented names (`build_pack`, `discover_packs`, `resolve_pack_entrypoint`, `validate_pack_name`).
- Updated defaults to `packs/` and removed old `functions` naming from current usage.

## 0.2.1

- Removed hard-coded first-party roots (`functions`, `app`, `lib`) in favor of local import resolution under project root.
- Kept `functions/` as the required entrypoint directory while allowing runtime imports from sibling local modules/packages.
- Excluded `tests/` from runtime first-party traversal and updated docs/tests for the new import-following behavior.

## 0.1.0

- Initial public packaging baseline for `monopack`.
- Added CLI `--version` support (`monopack --version`).
- Added publishing dry-run workflow docs for `python -m build` and `python -m twine check dist/*`.
