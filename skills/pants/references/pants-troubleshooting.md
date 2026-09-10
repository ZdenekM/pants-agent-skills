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
`shadowed_caches` and `pex_roots` are reported for information; neither is a
deletion target in its own right. One caveat: a pex root nested inside a cache
category -- `<named_caches_dir>/pex_root`, or a `PEX_ROOT` pointed inside it --
is removed along with its parent when that category's limit is exceeded. Such an
entry is reported with `inside_named_caches: true` and a note saying so.

## Resolve Cache Paths From Effective Config

`pants.toml` is not authoritative on its own. Pants reads `pantsrc_files`
(`/etc/pantsrc`, `~/.pants.rc`, `.pants.rc` by default) after it, then `PANTS_*`
environment variables. Confirm the live location before measuring or deleting:

```bash
pants --no-pantsd help-advanced global
```

Each overridden option prints `current value: <path> (<source>)`.

When a cache option is redirected this way, Pants stops using the directory
named in `pants.toml` but never removes it. The old location stays on disk at
full size and reads as if it were the live cache. A repo-relative default such
as `.pants.d/lmdb_store` also leaves one copy per git worktree. The helper
lists these under `shadowed_caches` with size and newest mtime; verify against
`help-advanced global` before deleting one.

When clearing a shadowed repo-local cache, delete only the redirected cache
subdirectories. `pants_workdir` (`.pants.d/workdir`) and `.pants.d/pids` stay
per-build-root whatever the cache options say, and they are live state.

## Cache Size Limits Do Not Cover Everything

`local_store_*_max_size_bytes` bound `local_store_dir`, and Pants garbage-
collects it to one tenth of their sum. Nothing bounds `named_caches_dir`. Its
`pex_root` subtree grows without limit as resolves change, which makes it the
usual source of unexplained growth once the local store is capped.

## Pruning PEX Caches

Do not prune a pex root with `find -mtime`. Wheels are installed once and
hardlinked into every venv that uses them, so an old mtime does not mean an
entry is unreferenced, and archive extraction can leave files dated decades in
the future. Use the reference-aware pruner, which keeps its own last-access
markers:

```bash
pex3 cache prune --older-than "60 days" -n --pex-root <root>
pex3 cache prune --older-than "60 days" --pex-root <root>
```

Drop `-n` only after reviewing the dry run. Prune each root separately: the
Pants-managed one at `<named_caches_dir>/pex_root`, and any user-level
`PEX_ROOT` (current pex defaults to the platform cache directory; older
versions used `~/.pex`). Never prune while a Pants command is running, and note
that pex takes a cache write lock that blocks until every other pex process
exits -- a long-running `pants run ...:server` will stall the prune, so stop it
or skip that root.

The totals `pex3 cache prune` reports are apparent sizes, not reclaimed disk.
Most of a pex root is `installed_wheels`, and a venv's content is hardlinked to
it, so pruning venvs frees far less than the printed figure. Measure the root
with `du -sh` before and after to learn the real number; a run reporting 16.6 GB
pruned can return roughly 2 GB.

Two failure modes worth planning for:

- Entries written by an older pex version can lack the `.last-access` marker,
  and the prune aborts on the first one with `No such file or directory:
  .../.last-access`. Widen the cutoff, or recreate the missing markers with
  `touch -r <entry-dir> <entry-dir>/.last-access` so the recorded access time
  matches the directory rather than now. Never fall back to manual deletion.
- Automate the prune non-fatally. One bad entry must not take down a scheduled
  sweep.

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

When measuring a pex root, count each inode once. Summing file sizes without
deduplicating hardlinks overstates it several-fold and makes size-based limits
fire on bytes that are not there. `du` and the bundled helper both deduplicate;
a plain file-size walk does not.

## Parallelism And Shared Resources

For tests that share ports, databases, GPUs, or external services, prefer the
repo's established mechanism such as `execution_slot_var` or a targeted
parallelism option. As a last resort for a specific run:

```bash
pants --process-execution-local-parallelism=1 test <spec>
```

Do not globally reduce parallelism without evidence.
