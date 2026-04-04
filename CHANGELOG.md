# Changelog

## 0.2.1

- Removed hard-coded first-party roots (`functions`, `app`, `lib`) in favor of local import resolution under project root.
- Kept `functions/` as the required entrypoint directory while allowing runtime imports from sibling local modules/packages.
- Excluded `tests/` from runtime first-party traversal and updated docs/tests for the new import-following behavior.

## 0.1.0

- Initial public packaging baseline for `monopack`.
- Added CLI `--version` support (`monopack --version`).
- Added publishing dry-run workflow docs for `python -m build` and `python -m twine check dist/*`.
