# Local Pants Patterns

Read-only survey date: 2026-05-18.

This document is development input for the reusable skill. It is not installed
with the skill bundle and should not become a source of project-specific rules.

## Survey Scope

The local survey covered 11 Pants build roots across application, service,
research, and UI repositories. Repository names and paths are intentionally
omitted from this public development note; the purpose is to preserve reusable
workflow patterns, not local project identity.

Observed patterns:

| Pattern | Examples of variation |
| --- | --- |
| Pants versions | active repos spanned 2.18.x through 2.31.x |
| Source roots | `/`, product subtrees, research subtrees, script folders, generated/IDL roots, and multi-root layouts |
| Dependency layout | root requirements, `3rdparty/` requirements, Python resolves, tool lockfiles, and single-resolve repos |
| Backend coverage | Python-only, Python plus shell, Python plus Docker, and Protobuf/codegen backends |
| Workflow signals | changed-since CI, full repo CI gates, path-filtered CI, repo-local cache policy, serialized Pants runs, helper targets, and local plugins/macros |

No executable repo-local `./pants` wrapper was found in the shallow survey, so
the sampled projects currently lean on `pants` from `PATH` or CI-provided setup.
The reusable skill should still prefer `./pants` when a future repository has a
wrapper.

## Reusable Implications

1. Source roots vary enough that `pants roots` must be a first-class step.
2. Runner choice is a per-repo fact; never carry `pants` vs `./pants` across windows.
3. Lockfiles appear at the build root, under `pants/`, and under `3rdparty/`.
4. Some CI workflows are path-filtered, so new Pants-managed subtrees need CI trigger review.
5. Several repos treat Pants as heavyweight; the generic skill should teach serialization when the repo asks for it, not enforce one global parallelism policy.
6. `tailor` and `update-build-files` both appear in active workflows; the skill should mention both and let the repo version decide exact usage.
7. Docker and shell are first-class local Pants use cases; the skill should inspect enabled backends before assuming a Python-only workflow.
8. Local plugin/macro surfaces and `pants run` helper targets show up in real workflows; the skill should teach inspection and adaptation, not assume only built-in Pants target types.
9. Codegen/IDL backends appear in local repos; the skill should teach agents to inspect source roots and generated-code semantics before looking for checked-in outputs.

## Do Not Generalize

- Do not hardcode local repo names into the installed skill.
- Do not assume `research`, `/`, `src`, or any other source root.
- Do not assume lockfile names such as `python-default.lock`, `lockfile.txt`, or `3rdparty/*_lockfile.txt`.
- Do not assume CI always runs on every PR path; inspect workflow filters.
- Do not copy repo-specific smoke tests, tags, package targets, or agent policies into the generic skill.
- Do not run `docker build` or shell scripts directly when Pants owns the corresponding `docker_image`, `shell_source`, or command target unless repo instructions explicitly say so.
- Do not treat unknown BUILD symbols as errors before checking local plugins, macros, and enabled backend packages.
- Do not assume generated Protobuf/codegen output is checked in; use Pants introspection or `export-codegen` when needed.
