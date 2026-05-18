# Pants Python Workflow

## Python Targets

Common target types:

- `python_sources`
- `python_tests`
- `python_requirements`
- `python_requirement`
- `pex_binary`
- `python_distribution`

Prefer target generators where they match the repo's existing style. After
adding files, use `pants tailor <path>` or `pants update-build-files <path>`
when BUILD metadata may need regeneration.

## Third-Party Dependencies

Do not rely on an activated virtualenv as the source of truth. Inspect the repo
inputs that Pants uses:

- `requirements.txt` or custom requirements files,
- PEP 621 `pyproject.toml`,
- Poetry inputs,
- `3rdparty/**/BUILD`,
- `python_requirement` or `python_requirements` targets,
- tool-specific requirements files.

When import names do not match distribution names, look for existing
`module_mapping` or `modules` patterns and extend those directly.

## Resolves And Lockfiles

Before changing dependencies, inspect:

```bash
pants help python
pants help python-repos
pants help generate-lockfiles
```

Check `[python] enable_resolves`, `default_resolve`, and `resolves` in
`pants.toml`. Repositories may keep runtime and tool resolves in different
lockfiles. Some keep lockfiles at the build root; others keep them under
`3rdparty/`.

Regenerate the narrowest affected resolve:

```bash
pants generate-lockfiles --resolve=<resolve-name>
```

Regenerate all lockfiles only when the repo contract requires it or the change
really crosses resolve boundaries.

## Tool Lockfiles

Formatters, linters, type checkers, pytest, setuptools, and other tools may use
dedicated resolves or `install_from_resolve`. When tool dependencies change,
update the tool's declared input and its matching lockfile, not an unrelated
runtime lockfile.

## Pytest And Runtime Data

Pass pytest args after `--`:

```bash
pants test path/to/test_file.py -- -k 'case_name' -vv
```

Common missing-dependency causes:

- test utility or `conftest.py` not owned by the expected target,
- runtime data not declared as `resource`, `file`, or explicit dependency,
- first-party code and requirements assigned to different resolves,
- source root mismatch,
- generated or ignored files absent from the sandbox.

Use `pants dependencies`, `pants filedeps`, and sandbox inspection before adding
manual dependency excludes.

## IDE Export

`pants export` can help an IDE, but exported virtualenvs are derived artifacts.
Do not edit them or treat them as the dependency source of truth.
