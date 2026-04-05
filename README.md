# monopack

`monopack` builds per-pack Python Lambda bundles from a monolith-style repo.

## Background

Go works well for multi-Lambda projects because one codebase can expose multiple `cmd` entrypoints and build each pack with only what it needs.

Python workflows are usually less ergonomic at that scale:

- AWS SAM and Serverless framework commonly package one Python artifact per project.
- Per-pack folder layouts can make shared code awkward.
- Workarounds such as local packages, symlinks, or copied shared folders often add maintenance overhead.

`monopack` is intended to make Python feel closer to that Go workflow without changing your project into N separate services. It takes a larger codebase and produces per-pack zip artifacts by:

- tracing imports from each pack entrypoint,
- copying reachable first-party files,
- deriving a minimal pinned `requirements.txt` subset for third-party imports,
- installing only that dependency subset into the build target,
- and running optional verification/tests to increase confidence that each split artifact works in isolation.

It is intentionally conservative: this is import-based trimming with guardrails, not full tree-shaking or whole-program optimization. It aims to cover common Python import patterns used in real projects, while keeping behavior explicit and testable.

## What monopack does

- Builds one or many packs from `packs/*.py` into `build/<pack_name>/`.
- In `deploy` mode, writes deploy zip artifacts at `build/<pack_name>.zip`.
- In `deploy` mode, writes package digest helper file(s) (`build/<pack_name>.package.sha256` by default).
- In `test` mode, copies relevant tests and runs them in the build target (no zip output).
- Uses pinned project `requirements.txt` (`name==version` lines only).
- Supports optional auto-fix for missing-module verification failures (`--auto-fix`, opt-in).

## Quickstart

Project expectations:

- `packs/` directory with pack entrypoint files (`<name>.py`).
- Project-level `requirements.txt` containing pinned `name==version` lines.
- Optional `tests/` directory when using `--mode test`.

Build one pack in deploy mode:

```bash
PYTHONPATH=src python -m monopack users_get \
  --packs-dir packs \
  --build-dir build
```

Run confidence build in test mode:

```bash
PYTHONPATH=src python -m monopack users_get \
  --packs-dir packs \
  --build-dir /tmp/monopack-build \
  --mode test
```

Build all packs discovered in `packs/*.py` (no target argument):

```bash
PYTHONPATH=src python -m monopack \
  --packs-dir packs \
  --build-dir build
```

## CLI usage

Basic form:

```bash
PYTHONPATH=src python -m monopack [pack_name] [options]
```

Key flags for real-project usage:

- `--version`: prints the installed `monopack` version and exits.
- `--mode deploy|test`: deploy builds runtime payload + zip; test builds payload + tests (no zip).
- `--with-tests`: deploy mode only; runs relevant tests before finalizing deploy payload.
- `--verify` / `--no-verify`: verifier is on by default.
- `--auto-fix`: opt-in auto-repair loop for missing imports during verify.
- `--debug`: emit aggregated import/dependency resolution report to stderr.
- `--jobs`: parallel workers for multi-pack builds (`auto` default).
- `--sha-output`: comma-separated package digest outputs for deploy mode (`hex`, `b64`; default `hex`).

Package digest output guidance:

- `hex` (`.package.sha256`): general CI/script diffing and human-readable checks.
- `b64` (`.package.sha256.b64`): Terraform-style workflows that prefer base64 digest values.
- Use both when needed: `--sha-output hex,b64`.

For full argument behavior and validation details, see `docs/cli.md`.

## Constraints and limits

- Function discovery is shallow: only `packs/*.py` (excluding names starting with `_`).
- Pack names must use letters, numbers, and underscores; pack names cannot include `/`, `\\`, or `.`.
- Build directory must differ from packs directory and cannot be nested inside it.
- Requirements parser accepts only pinned `name==version` lines (comments and blanks allowed).
- First-party graph traversal follows imports that resolve to local modules under the same project root as `packs/` (excluding `tests/`).
- Auto-fix only handles `ModuleNotFoundError` flows and retries up to 3 times when enabled.

## Recommended feedback loop for monolith split confidence

1. Build the target in test mode with verification enabled:
   `PYTHONPATH=src python -m monopack <pack> --mode test --verify`.
2. Inspect build output (`build/<pack>/`) and generated `requirements.txt` for expected scope.
3. Build deploy artifact once confidence is good:
   `PYTHONPATH=src python -m monopack <pack> --mode deploy`.
4. Optionally gate deploy build with tests:
   `PYTHONPATH=src python -m monopack <pack> --mode deploy --with-tests`.
5. Run repository tests to catch broader regressions:
   `python -m unittest discover -s tests -v`.
6. Tighten imports/tests/inline config and repeat until scoped build behavior is stable.

## Deeper docs

- CLI reference: `docs/cli.md`
- PyPI publishing: `docs/publishing.md`
- Fixture-driven confidence loop and matrix: `docs/testing-fixtures.md`

For Terraform `source_code_hash` usage with generated package digests, see `docs/cli.md`.
