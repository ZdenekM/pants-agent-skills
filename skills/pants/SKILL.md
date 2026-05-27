---
name: pants
description: Work efficiently in repositories using Pants/Pantsbuild. Use when a repo has pants.toml, BUILD files, Pants lockfiles, Python resolves, source roots, dependency inference, hermetic sandboxes, Pants goals, Docker or shell backends, protobuf/codegen, local plugins/macros, or parallel workspace sessions that may point at different Pants build roots.
---

# Pants / Pantsbuild Workflow

Use this skill for the Pants build system. Always rediscover the active build root before applying Pants knowledge from another project.

## First Moves

1. Identify the active repository and Pants build root from the current `cwd`; do not reuse a prior window's runner, source roots, resolves, or target addresses.
2. Prefer an executable repo-local `./pants` wrapper. If none exists, use `pants` from `PATH`. Follow explicit repo instructions when they intentionally differ.
3. Inspect `pants.toml`, relevant `BUILD` files, repo instructions such as `AGENTS.md`, dependency inputs, lockfiles, and CI Pants workflows before changing Pants behavior.
4. Run `pants roots` before assuming `src`, `tests`, `research`, `/`, or any other source root.
5. Use narrow specs first: files, target addresses, directory specs, then changed specs. Use `::` for final verification or when the repo is small enough.

## Probe The Repo

Run the bundled tracked-file-safe probe when orientation matters:

```bash
python <skill-dir>/scripts/pants_repo_probe.py --pretty
```

Use the script path from the loaded or installed skill bundle, not from the target Pants repository. The probe prints JSON and does not edit tracked project files, but its default `pants --version` and `pants roots` calls may create local cache or daemon state. Use `--files-only` when Pants commands should not run. If the repo requires serialized Pants work or another Pants command is active, wait, reuse the active run, or start with `--files-only`.

## Core Commands

- `pants help goals`, `pants help subsystems`, `pants help <goal-or-subsystem>`
- `pants roots`
- `pants list <spec>`
- `pants dependencies [--transitive] <target>`
- `pants dependents [--transitive] <target>`
- `pants filedeps <target>`
- `pants peek [--exclude-defaults] <target>`
- `pants paths --from=<target-a> --to=<target-b>`
- `pants tailor <spec>` and `pants update-build-files <spec>`
- `pants fmt|fix|lint|check|test|run|package <spec>`
- `pants export-codegen <spec>` when generated sources must be inspected outside Pants
- `pants generate-lockfiles --resolve=<resolve>`

## BUILD, Backend, And Packaging Rules

Prefer target generators and backend-native targets such as `python_sources`, `python_tests`, `python_requirements`, `shell_sources`, `protobuf_sources`, `docker_image`, `pex_binary`, and `python_distribution`. Avoid overlapping `sources` globs. Add explicit dependencies for resources, files, Docker build context inputs, shell scripts, generated/IDL sources, packaged artifacts, runtime data, plugins, and non-import relationships that dependency inference cannot see. Use `!address` only to suppress a known false inferred dependency.

Do not treat an ambient virtualenv, ad hoc Docker invocation, checked-in generated code, or standalone shell command as the source of truth when Pants owns that workflow. Inspect enabled backends, local plugin/macro configuration, requirement generators, resolves, lockfiles, module mappings, Dockerfile dependencies, shell command tools, codegen/protobuf settings, interpreter constraints, and tool lockfiles. Regenerate the narrowest affected lockfile.

## Debugging

For difficult failures, add `--print-stacktrace -ldebug` and use `--keep-sandboxes=on_failure`. Inspect the sandbox contents and `__run.sh`. For daemon/cache suspicion, try `--no-pantsd` before deleting caches. Explain the effect before removing `.pants.d`, named caches, local stores, or global Pants caches.

## Parallel Workspaces

Treat every editor window, terminal, agent session, or workspace as a separate Pants project. Re-probe `cwd`, build root, runner, version, source roots, resolves, and target addresses. Do not update global Pants config or delete global caches unless explicitly requested. Use unique temp files and avoid cross-project assumptions. When a repo says Pants is heavyweight or lock-prone, serialize all Pants commands in that repo, including read-only discovery.

## References

- Read `references/pants-core-workflow.md` for build root discovery, target selection, introspection, and verification flow.
- Read `references/pants-python.md` for Python requirement targets, resolves, lockfiles, tool lockfiles, and pytest behavior.
- Read `references/pants-docker-shell.md` for Docker images, shell scripts, shell commands, linting, and package verification.
- Read `references/pants-troubleshooting.md` for import errors, sandbox failures, cache/pantsd diagnosis, and parallelism issues.
- Read `references/parallel-pants-workspaces.md` when multiple Pants repos, workspaces, windows, or agent sessions are active.
- Read `references/sources.md` when you need current upstream documentation links.
