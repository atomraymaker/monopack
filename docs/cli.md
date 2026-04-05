# CLI reference

## Command

```bash
PYTHONPATH=src python -m monopack [pack_name] [options]
```

Exit codes:

- `0` on success
- `2` on validation/build input errors

## Arguments and flags

| Argument | Type | Default | Behavior |
| --- | --- | --- | --- |
| `--version` | flag | n/a | Print installed CLI version and exit. |
| `pack_name` | positional, optional | `None` | Build one pack (`packs/<name>.py`). If omitted, discover and build all packs in `packs_dir`. |
| `--packs-dir` | path | `packs` | Directory containing entrypoints. `project_root` is derived from its parent. |
| `--build-dir` | path | `build` | Output base dir. Each pack builds to `<build_dir>/<pack_name>/`. |
| `--mode` | `deploy` or `test` | `deploy` | `deploy`: runtime payload + zip. `test`: runtime payload + relevant tests (no zip). |
| `--with-tests` | flag | `False` | Deploy mode only. Runs relevant tests before finalizing deploy payload. |
| `--verify` / `--no-verify` | mutually exclusive flags | verify on | Controls verifier script execution. |
| `--auto-fix` | flag | `False` | Opt-in auto-fix loop for missing-module verifier failures. |
| `--debug` | flag | `False` | Print aggregated build/import resolution diagnostics to stderr. |
| `--jobs` | `auto` or integer | `auto` | Parallel workers for multi-pack builds. `auto` picks a conservative core-based value (capped) and falls back to serial with `--auto-fix`. |
| `--sha-output` | comma list (`hex`,`b64`) | `hex` | Deploy-mode package digest output(s): `build/<pack>.package.sha256` and/or `build/<pack>.package.sha256.b64`. |

## Environment variables

CLI flags override env vars. Env vars override built-in defaults.

- `MONOPACK_PACKS_DIR`
- `MONOPACK_BUILD_DIR`
- `MONOPACK_MODE` (`deploy` or `test`)
- `MONOPACK_VERIFY` (`1/0`, `true/false`, `yes/no`)
- `MONOPACK_AUTO_FIX` (`1/0`, `true/false`, `yes/no`)
- `MONOPACK_WITH_TESTS` (`1/0`, `true/false`, `yes/no`)
- `MONOPACK_DEBUG` (`1/0`, `true/false`, `yes/no`)
- `MONOPACK_JOBS` (`auto` or positive integer)

## Validation rules

- `packs_dir` must exist and be a directory.
- `build_dir` must differ from `packs_dir` and cannot be nested inside it.
- `<project_root>/requirements.txt` must exist and be a file.
- Pack names must match `^[a-zA-Z0-9_]+$`.
- Target names cannot contain `/`, `\\`, or `.`.
- `--with-tests` is valid only with `--mode deploy`.
- `--mode test` or `--with-tests` requires `<project_root>/tests/` to exist.

## Examples

Deploy one pack:

```bash
PYTHONPATH=src python -m monopack users_get --mode deploy
```

Test-mode confidence build:

```bash
PYTHONPATH=src python -m monopack users_get --mode test
```

Deploy build with test gate:

```bash
PYTHONPATH=src python -m monopack users_get --mode deploy --with-tests
```

Enable auto-fix locally:

```bash
PYTHONPATH=src python -m monopack users_get --mode deploy --auto-fix
```

Emit both digest formats for deploy pipelines:

```bash
PYTHONPATH=src python -m monopack users_get --mode deploy --sha-output hex,b64
```

Terraform (`source_code_hash`) change-trigger example:

```hcl
resource "aws_lambda_function" "users_get" {
  function_name    = "users_get"
  filename         = "build/users_get.zip"
  source_code_hash = trimspace(file("build/users_get.package.sha256.b64"))
  # ...
}
```

Use `--sha-output b64` (or `hex,b64`) when your deploy tooling expects base64 digest strings.

GitHub Actions sketch (deploy only when digest changed):

```yaml
name: build-and-deploy

on:
  push:
    branches: [main]

jobs:
  package:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: python -m pip install -e .
      - run: PYTHONPATH=src python -m monopack users_get --mode deploy --sha-output b64
      - id: digest
        run: |
          echo "value=$(tr -d '\n' < build/users_get.package.sha256.b64)" >> "$GITHUB_OUTPUT"
      - name: Deploy
        if: ${{ steps.digest.outputs.value != vars.USERS_GET_DEPLOYED_HASH_B64 }}
        run: |
          echo "Run deploy here"
```
