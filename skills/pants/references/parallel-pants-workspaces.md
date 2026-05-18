# Parallel Pants Workspaces

## Contract

Every editor window, terminal, agent session, or workspace is a separate Pants
context. Before each Pants command series, re-check:

- current working directory,
- nearest `pants.toml`,
- runner choice (`./pants` vs `pants`),
- Pants version,
- source roots,
- resolves and lockfiles,
- relevant repo instructions.

Do not carry target addresses, resolve names, source roots, or lockfile names
from one repository to another.

## Global State

Do not write global Pants config, shell startup files, or shared cache settings
unless the user explicitly asks. Read local `.pants.rc`, `.pants.bootstrap`, or
repo instructions as local policy only.

Avoid global cleanup commands while another Pants repo may be active. If cache
cleanup is needed, prefer repo-local `.pants.d` paths when the repo uses them.

## Temp Files

Use unique temp files for generated specs or helper output. Safe patterns:

- repo-local ignored temp directories,
- `mktemp`,
- Python `tempfile`.

Avoid fixed shared names such as `/tmp/pants-specs.txt`.

## Concurrency

Some repos tolerate concurrent Pants work; others explicitly treat Pants as a
heavyweight or lock-prone resource. If a repo says to serialize Pants commands,
do that. If multiple heavy jobs are already running, prefer polling/reusing the
active run, focused specs, or waiting over starting duplicate broad checks.

## Reporting

Final summaries should include the build root, exact Pants commands run, and any
checks skipped with reasons. This is especially important when multiple Pants
repos or agent sessions are active at the same time.
