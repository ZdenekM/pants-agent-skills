# Pants Troubleshooting

## First Diagnosis

Prefer targeted diagnosis before cache deletion or global changes:

```bash
pants --print-stacktrace -ldebug <goal> <spec>
pants --keep-sandboxes=on_failure <goal> <spec>
pants --no-pantsd <goal> <spec>
```

Use `--keep-sandboxes=always` only when repeated sandbox inspection is needed.

## Import Errors

Check in this order:

1. source root from `pants roots`,
2. owner target with `pants list path/to/file.py`,
3. direct and transitive dependencies,
4. requirement target and lockfile membership,
5. import-name to distribution-name mapping,
6. resolve compatibility between first-party and third-party targets.

Avoid adding `# pants: no-infer-dep` or `!address` before understanding the
actual ownership or resolve problem.

## Missing Files And Resources

If a command works outside Pants but fails in Pants, inspect the sandbox. Missing
files usually need a `resource`, `file`, generated target, or explicit
dependency. Also check `.gitignore`, `pants_ignore`, and generated-output paths.
When generated code is expected on disk, verify whether Pants only materializes
it inside the sandbox; use `pants export-codegen` only when external inspection
is needed.

## Target Ownership Ambiguity

Multiple owners often come from overlapping `sources` globs or too many manual
targets. Prefer simplifying the BUILD metadata and using target generators over
patching around ambiguity.

## Sandbox Workflow

After a sandbox failure:

1. copy the sandbox path from the log,
2. list its files,
3. inspect `__run.sh` if present,
4. compare expected runtime inputs with declared target dependencies,
5. rerun the smallest failing spec after the metadata fix.

## pantsd And Cache

Treat invalidation debugging and size-based cleanup as separate workflows.

For suspected invalidation issues:

```bash
pants --no-pantsd <goal> <spec>
pants --no-local-cache <goal> <spec>
```

If `--no-pantsd` resolves the issue, restart the daemon by removing
`.pants.d/pids/` from the build root. Preserve `.pants.d/workdir/pantsd/` logs
and persistent cache contents when they may be useful for an upstream bug
report. Delete global cache directories only after targeted diagnosis and with
a clear explanation of cost.

For size-based cleanup, measure first:

```bash
python <skill-dir>/scripts/pants_cache_maintenance.py --pretty
python <skill-dir>/scripts/pants_cache_maintenance.py --limit launcher=512 --limit named_caches=1024 --apply
```

The helper is read-only unless `--apply` is provided, and it only deletes cache
categories with explicit `--limit NAME=MB` values that are exceeded.

## Cache Directory Map

- Launcher cache: `$HOME/.cache/nce` on Linux or
  `$HOME/Library/Caches/nce` on macOS. Cache it against the Pants version.
- `named_caches_dir`: defaults to `$HOME/.cache/pants/named_caches`; tools such
  as PEX store reusable tool data here. Cache it against tool inputs such as
  Python lockfiles.
- `local_store_dir`: defaults to `$HOME/.cache/pants/lmdb_store`; this stores
  local process results. In CI, preserve it only when the invalidation key is
  broad enough, or prefer remote caching for fine-grained reuse.
- `pants_workdir`: defaults to `.pants.d/workdir` under the build root. It holds
  logs and temporary workdir state and is not the persistent cache.
- `pants_distdir`: defaults to `dist/`. It holds package artifacts and is not a
  cache.

For `named_caches_dir` and `local_store_dir`, absolute paths are used directly;
relative paths are relative to the build root. In multi-repo work, global cache
cleanup can disturb other active Pants projects.

## Parallelism And Shared Resources

For tests that share ports, databases, GPUs, or external services, prefer the
repo's established mechanism such as `execution_slot_var` or a targeted
parallelism option. As a last resort for a specific run:

```bash
pants --process-execution-local-parallelism=1 test <spec>
```

Do not globally reduce parallelism without evidence.
