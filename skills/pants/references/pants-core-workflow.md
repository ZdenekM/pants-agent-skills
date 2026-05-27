# Pants Core Workflow

## Build Root Discovery

Start from the current working directory and locate the nearest parent containing
`pants.toml`. Do not assume that the git root and Pants build root are identical.
Prefer an executable `./pants` wrapper in the build root, then `pants` from
`PATH`.

Portable first step:

```bash
python <skill-dir>/scripts/pants_repo_probe.py --pretty
```

Use `--files-only` when Pants commands should not run; it still parses local
configuration but skips `pants --version` and `pants roots`.

If the probe is unavailable, these POSIX shell examples are useful first
commands:

```bash
pwd
git rev-parse --show-toplevel 2>/dev/null || true
find .. -maxdepth 3 -name pants.toml -print 2>/dev/null | head
./pants --version || pants --version
./pants roots || pants roots
./pants help goals || pants help goals
./pants help subsystems || pants help subsystems
```

Read repo instructions before edits: `AGENTS.md` or equivalent agent guidance,
`pants.toml`,
`pants.ci.toml`, root and nearby `BUILD` files, dependency inputs, lockfiles,
and CI workflows that run Pants.

## Configuration And Backends

Pants options can come from CLI flags, environment variables, config files, and
defaults. Inspect the effective local repo contract instead of copying commands
from another Pants repository.

Key config areas:

- `[GLOBAL] pants_version`
- `[GLOBAL] backend_packages` or `backend_packages.add`
- `[GLOBAL] plugins`, `pythonpath`, and `build_file_prelude_globs` for local plugins or macros
- `[source] root_patterns` and `marker_filenames`
- `[python] enable_resolves`, `default_resolve`, `resolves`
- codegen/tool subsystems such as `[python-protobuf]`, `[protoc]`, or `[buf]`
- CI-only config such as `pants.ci.toml` or `PANTS_CONFIG_FILES`

For Pants version audits, prefer the active runner (`pants --version` or the
repo-local wrapper), `pants.toml`, and upstream Pants sources listed in
`references/sources.md`. Do not treat `python -m pip index versions
pantsbuild.pants` as authoritative for a Pants 2 runner selection. After changing
`[GLOBAL] pants_version` in a repo without an executable wrapper, run
`pants --version` to prove the PATH runner can bootstrap the configured version.

## BUILD Files And Targets

Targets are addressable metadata in `BUILD` files. Prefer target generators and
backend-native targets such as `python_sources`, `python_tests`,
`python_requirements`, `shell_sources`, `protobuf_sources`, `docker_image`, `pex_binary`, and
language/tool-specific generators over manual per-file target sprawl.

Rules:

- Keep `BUILD` files declarative; avoid imports, file I/O, or runtime-dependent logic.
- Avoid overlapping `sources` globs that create multiple owners for one file.
- Add direct explicit dependencies only where inference cannot see the relation.
- Use `__defaults__`, `overrides`, and `parametrize` for local conventions when the repo already uses them.
- Run `pants tailor <path>` or `pants update-build-files <path>` after file moves/additions when BUILD metadata may drift.

## Source Roots

Treat source roots as configured facts:

```bash
pants roots
```

Also inspect `[source]` in `pants.toml`. Local repos may use `/`, `research`,
`src`, `tests`, product-specific roots, marker files, or several roots at once.

## Target Selection

Default preference:

1. concrete file path,
2. concrete target address,
3. directory spec,
4. `--changed-since=<rev>` plus `--changed-dependents=transitive`,
5. full `::` only for final verification or small repos.

For large repos, consider:

```bash
--filter-target-type=<type>
--filter-address-regex=<regex>
--filter-tag-regex=<regex>
--tag=<tag>
--spec-files=<file>
```

Generate spec files with unique repo-local or `mktemp` paths. Do not use a
fixed shared filename in `/tmp`.

## Introspection

Use Pants to inspect the graph instead of guessing:

```bash
pants list <spec>
pants dependencies <target>
pants dependencies --transitive <target>
pants dependents <target>
pants dependents --transitive <target>
pants filedeps <target>
pants peek <target>
pants peek --exclude-defaults <target>
pants paths --from=<target-a> --to=<target-b>
```

Prefer `--format=json` when available and when a script or `jq` will consume
the output.

## Codegen And IDL Backends

Some repos use Pants to generate language bindings from IDL sources such as
Protobuf. Do not assume generated files are checked in or stale just because
they are not present on disk; Pants may materialize them only inside sandboxes.

For codegen work:

- inspect enabled backends such as `pants.backend.codegen.protobuf.python` and
  linters such as `pants.backend.codegen.protobuf.lint.buf`,
- inspect source roots that include IDL folders,
- use `pants dependencies`, `pants peek`, and `pants filedeps` on the IDL and
  consuming targets,
- use `pants export-codegen <spec>` only when generated output needs external
  inspection or an IDE/tool cannot consume Pants's sandboxed generation,
- when redirecting `export-codegen` output, use a repo-relative `--pants-distdir`
  scratch directory; Pants rejects absolute dist dirs outside the build root,
- keep generated output out of source control unless the repo explicitly
  requires checked-in generated files.

## Repo-Specific Plugins, Macros, And Helper Targets

Some repos extend Pants through in-repo plugins, custom backend packages, or
BUILD-file macros. Inspect `backend_packages`, `plugins`, `pythonpath`,
`build_file_prelude_globs`, and nearby `pants-plugins/` before assuming a target
symbol is built into Pants.

Rules:

- Treat custom targets and macros as repo-local contracts. Read their docs or
  implementation before editing generated BUILD metadata.
- Do not copy plugin conventions from one repo to another.
- If plugin code changes, use the repo's plugin tests or the closest Pants
  goals that exercise the custom backend.
- For `pants run` helper targets, inspect the target with `pants peek`, pass
  runtime args after `--`, and remember that Pants propagates the process exit
  code.
- For long-running `pants run` processes, avoid starting duplicate instances;
  reuse, poll, or stop the existing process according to repo instructions.

## Verification Flow

Start focused and match the file type:

```bash
pants fmt path/to/changed.py path/to/BUILD
pants lint path/to/changed.py
pants check path/to/changed.py
pants test path/to/test_file.py
pants run path/to:helper -- --arg
pants lint path/to/script.sh
pants lint path/to/Dockerfile
pants package path/to:package_target
```

Then widen based on the change:

```bash
pants --changed-since=HEAD --changed-dependents=transitive check test
pants --changed-since=HEAD lint
```

`fmt` and `fix` modify files. After running either, inspect diff/status before
claiming completion. Packaging should include a runtime smoke or artifact
inspection, not only a successful `pants package`.
