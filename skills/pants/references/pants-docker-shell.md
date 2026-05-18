# Pants Docker, Shell, And Packaging Workflow

Use this reference when a Pants repo enables Docker or shell backends, owns
Dockerfiles, packages images/distributions, or uses shell commands as build
helpers.

## Backends To Inspect

Check `pants.toml` before assuming support:

- `pants.backend.docker`
- `pants.backend.docker.lint.hadolint`
- `pants.backend.experimental.docker.lint.trivy`
- `pants.backend.shell`
- `pants.backend.shell.lint.shfmt`
- `pants.backend.shell.lint.shellcheck`

Also inspect CI workflows and repo instructions. Some repos package Docker
images only in CI, some lint shell scripts but keep operational scripts outside
Pants, and some require external tools such as Docker, ROS, or platform-native
launchers.

## Docker Images

Common targets and files:

- `docker_image`
- `Dockerfile` or custom `source=...`
- `files`, `file`, `pex_binary`, `python_distribution`, `archive`, or other
  packaged targets used as image dependencies

Pants assembles Docker build context from target dependencies. Do not replace
that with a manual `docker build` unless the repo explicitly uses Docker outside
Pants for that path.

Useful commands:

```bash
pants list path/to/Dockerfile
pants peek path/to:docker_target
pants dependencies path/to:docker_target
pants filedeps path/to:docker_target
pants lint path/to/Dockerfile
pants package path/to:docker_target
```

For broad Docker packaging in large repos, prefer target filters:

```bash
pants --filter-target-type=docker_image --changed-since=HEAD --changed-dependents=transitive package
```

Check repo policy for image tags, repositories, registries, build args, and
whether publishing is intentionally separate from `package`. Building an image
is not the same as validating it runs; add a repo-appropriate smoke or artifact
inspection when the change affects runtime behavior.

## Shell Sources And Shell Tests

Common targets:

- `shell_source`
- `shell_sources`
- `shell_test` / `shell_tests` depending on repo Pants version
- `shunit2_tests` in repos or docs that use shUnit2 naming

Useful commands:

```bash
pants list path/to/script.sh
pants lint path/to/script.sh
pants test path/to/script_test.sh
```

When changing shell scripts, inspect enabled linters. `shfmt` can reformat
files; `shellcheck` reports semantic warnings. Run `fmt`/`fix` only when you are
prepared to review the diff.

## Shell Commands

Pants can model command helpers through targets such as `shell_command` or
`run_shell_command` depending on the repo/version/plugin surface. These run in a
Pants sandbox and should declare the needed tools, inputs, outputs, and
dependencies.

Before changing a shell command target:

1. inspect `pants peek <target>`,
2. check `tools`, `dependencies`, `output_files`, and `output_directories`,
3. make the command idempotent because Pants may rerun it,
4. avoid relying on undeclared files from the developer machine,
5. verify the exact target with `pants run <target>` or the repo's documented
   command.

## Packaging Beyond Docker

`pants package` can also build Python distributions, PEX binaries, archives, and
other artifacts. For packaging changes, inspect target type and output path:

```bash
pants peek <target>
pants package <target>
```

Then check the produced artifact under `dist/` and run the smallest meaningful
runtime smoke. For Python distribution changes in large repos, filters such as
`--filter-target-type=python_distribution` can keep validation focused.

## Cross-Platform Caution

Do not turn POSIX shell convenience wrappers into required operator entrypoints
in repos that support Windows or packaged launchers. If repo instructions
distinguish Linux developer helpers from cross-platform operator tools, preserve
that boundary.
