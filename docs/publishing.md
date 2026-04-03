# Publishing to PyPI

This project is setuptools-based and publishes from `pyproject.toml` metadata.

## 1) Bump version

Update both version locations so package metadata and runtime version stay aligned:

- `pyproject.toml` -> `[project].version`
- `src/monopack/__init__.py` -> `__version__`

Keep the two values identical (for example, `0.1.1`).

## 2) Build artifacts

From repository root:

```bash
python -m build
```

Expected artifacts are created under `dist/`:

- source distribution: `dist/monopack-<version>.tar.gz`
- wheel: `dist/monopack-<version>-py3-none-any.whl`

If `dist/` contains older files, clean them first to avoid publishing stale artifacts.

## 3) Check artifacts with twine

```bash
python -m twine check dist/*
```

Only continue if twine reports all files as valid.

## 4) Publish

Upload to production PyPI:

```bash
python -m twine upload dist/*
```

Common cautions:

- PyPI releases are immutable; you cannot overwrite an existing version.
- Verify credentials are for the intended index/account before upload.
- Ensure metadata links in `pyproject.toml` (`Homepage`, `Repository`, `Issues`) are correct for public consumers.
- Prefer a TestPyPI dry run first when changing packaging metadata or build backend settings.

Optional TestPyPI upload:

```bash
python -m twine upload --repository testpypi dist/*
```
