# Testing fixtures

## Intended feedback loop

1. Add or update a fixture under `tests/fixtures/<name>/`.
2. Run the CLI against that fixture in test mode (`--mode test --verify`) so the build includes scoped tests and runs verifier + `unittest` inside the build target.
3. Run the full repository test suite (`python -m unittest discover -s tests -v`).
4. Tighten fixture or implementation constraints (imports, requirements, inline config, test selection) and repeat.

## Fixture matrix

| Fixture | Purpose | Key files | Modes tested | Third-party deps involved |
| --- | --- | --- | --- | --- |
| `simple` | Baseline single-function packaging and CLI happy path. | `functions/users_get.py`, `requirements.txt` | deploy | none |
| `shared_code` | Reachability walk across first-party modules. | `functions/users_get.py`, `app/users/service.py`, `app/shared/auth.py` | deploy | none |
| `third_party` | Requirement filtering + pip install trigger for direct imports. | `functions/users_get.py`, `requirements.txt` | deploy | `requests` |
| `relative_imports` | Relative import resolution across nested packages. | `functions/users_get.py`, `app/handlers/user_handler.py`, `app/services/profile.py` | deploy | none |
| `cycles` | First-party import cycle traversal without infinite recursion. | `functions/users_get.py`, `app/cycle/alpha.py`, `app/cycle/beta.py` | deploy | none |
| `transitive_deps` | Third-party dependency detection through transitive first-party imports. | `functions/users_get.py`, `app/shared/http.py`, `requirements.txt` | deploy | `requests` |
| `test_mode` | Test-mode copy + requirement union from runtime and relevant tests. | `functions/users_get.py`, `tests/test_users.py`, `requirements.txt` | deploy + test | runtime: `requests`; test-only: `colorama` |
| `monorepo_split` | Per-function test scoping and per-function test-only requirements in a multi-function repo. | `functions/users_get.py`, `functions/billing_charge.py`, `tests/users/test_users_get.py`, `tests/billing/test_billing_charge.py` | test | runtime: `requests`; test-only: `colorama` (users), `idna` (billing); excluded unrelated: `urllib3` |
| `config_overrides` | Inline config overrides for dynamic imports and explicit extra distributions. | `functions/users_get.py` (managed block), `app/hidden/runtime_dep.py` | deploy | `PyYAML` |
| `auto_fix_first_party` | Auto-fix for missing first-party module by rewriting inline config. | `functions/users_get.py`, `app/hidden/runtime_dep.py` | deploy | none |
| `auto_fix_third_party` | Auto-fix for missing third-party module by adding distribution to inline config. | `functions/users_get.py`, `requirements.txt` | deploy | `requests` |
| `kitchen_sink` | End-to-end mixed scenario: multi-function project, scoped tests, deploy/test mode split, inline config, and auto-fix. | `functions/users_get.py`, `functions/billing_charge.py`, `functions/reports_refresh.py`, `tests/users/test_users_get.py`, `tests/billing/test_billing_charge.py` | deploy + test | runtime: `requests`; test-only: `colorama`, `idna`; excluded unrelated: `urllib3` |

## Current constraints and limits

- CLI path validation requires:
  - existing `functions/` directory,
  - project-level `requirements.txt` file,
  - `build_dir` different from and not nested under `functions_dir`,
  - `tests/` directory when `--mode test` is used.
- Function naming rules:
  - target names must be bare identifiers (no `/`, `\\`, or `.`),
  - discovered/target names allow only letters, digits, and underscores.
- Function discovery is shallow (`functions/*.py` only), excluding files prefixed with `_`.
- Builder scope follows imports that resolve to local modules under the same project root as `functions/` (excluding `tests/`) plus optional `extra_modules` from inline config.
- Requirements handling accepts only pinned `name==version` lines (comments/blank lines allowed); unsupported forms (`>=`, extras, `-r`, VCS URLs, editable installs) raise errors.
- Verification behavior:
  - verifier imports selected modules + `functions.<name>` and asserts `lambda_handler` exists,
  - in test mode, relevant tests are copied by import relationship and executed with `python -m unittest discover -s tests -v` from the build target,
  - test files are selected from `tests/**/test*.py`; unrelated tests are excluded.
- Auto-fix behavior is limited to missing-module failures (`ModuleNotFoundError`), rewrites the `# monopack-start` managed block, and retries up to 3 times when `--auto-fix` is enabled.

## Adding new fixtures

- Add a focused fixture when you need to lock down one behavior or one regression axis (for example: import parsing edge case, requirements parsing failure mode, or a specific test-selection rule).
- Extend `kitchen_sink` only when the behavior must coexist with other real-world interactions (multi-function scoping, mixed runtime/test deps, inline config, auto-fix).
- Keep fixtures intentionally small: only include files needed to demonstrate reachability, dependencies, and expected copied tests.
- Prefer assertions on observable build outputs (`build/<fn>/...`, generated `requirements.txt`, rewritten inline config block) over internal implementation details.
